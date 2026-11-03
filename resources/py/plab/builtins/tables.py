"""table and timetable: columns of data (variables) of any class, one row
per observation, with names, optional row names (or row times) and
properties. A value object: indexing, assignment and concatenation make
new ones (vobj.py connects it to the engine as it does datetime).

T(rows, vars) is a table, T{rows, vars} the variables' data side by side,
T.Var a variable; rows and vars are numbers, logical masks, ':' or names."""
import csv
import io
import math
import os

import numpy as np

from . import bi
from ._util import err, nargchk, darr, out, num, opt_str, is_str, sval, ival
from ..values import (MError, Char, Str, Cell, Struct, F64, numel, shape_of, class_of, py_str, text_list, COLON,
                      FH, is_empty_double, share)
from ..vobj import VObj
from .. import runtime as R


def _rows_arg(rows):
    """0-based row positions as the language's index (a column of numbers)."""
    return out((np.asarray(rows, float) + 1).reshape(-1, 1))


def _height(v):
    return shape_of(v)[0] if len(shape_of(v)) else 1


def _take_rows(v, rows):
    from ..index import idx
    r = idx(v, (_rows_arg(rows), COLON))
    if type(r) in (float, bool, complex):
        r = np.array([[r]], dtype=bool if type(r) is bool else complex if type(r) is complex else float)
    return r


def _pick_rows(v, idxs):
    """The rows of v at idxs (0-based), a missing value's row where an index is None (or negative)."""
    idxs = [None if i is None or i < 0 else int(i) for i in idxs]
    if all(i is not None for i in idxs):
        return _take_rows(v, idxs)
    base = _cat_rows([_take_rows(v, list(range(_height(v)))), _missing_like(v, 1)])
    last = _height(v)
    return _take_rows(base, [last if i is None else i for i in idxs])


def _missing_like(v, n):
    """n rows of v's class standing for missing (NaN, '', <missing>, NaT, undefined)."""
    from ..vobj import VObj as _V
    w = shape_of(v)[1] if len(shape_of(v)) > 1 else 1
    t = type(v)
    if isinstance(v, _V):
        return v.empty_like((n, w))
    if t is Cell:
        c = np.empty((n, w), object)
        for i in range(c.size):
            c.flat[i] = Char.of('')
        return Cell(c)
    if t is Str:
        return Str(np.full((n, w), None, object))
    if t is Char:
        return Char(np.full((n, max(w, 0)), 32, np.uint16))
    a = np.asarray(v)
    if a.dtype.kind == 'f' or a.dtype.kind == 'c':
        return np.full((n, w), np.nan, a.dtype)
    if a.dtype == bool:
        return np.zeros((n, w), bool)
    return np.zeros((n, w), a.dtype)


def _cat_rows(vals):
    from ..ops import cat
    vals = [v if type(v) not in (float, bool, complex) else np.array([[v]]) for v in vals]
    return cat(0, vals)


def _cat_cols(vals):
    from ..ops import cat
    vals = [v if type(v) not in (float, bool, complex) else np.array([[v]]) for v in vals]
    return cat(1, vals)


def _valid_name(n):
    import re
    return bool(re.fullmatch(r'[A-Za-z]\w{0,62}', n))


def _texts(v, fn):
    if type(v) is Char:
        return [v.str()] if v.a.shape[0] <= 1 else v.row_strs()
    if type(v) in (Str, Cell):
        return text_list(v)
    raise err(f'MATLAB:{fn}:InvalidNames', 'The names must be text.', fn)


class Table(VObj):
    cls = 'table'
    ARRAYS = ()
    FUNCS = {}
    DIMS = ['Row', 'Variables']

    def __init__(self, vars_, names, rownames=None, n=None):
        # the variables are held here and perhaps elsewhere: a change copies them
        self.vars = [share(v) for v in vars_]
        self.names = list(names)
        self.rownames = list(rownames) if rownames is not None else None
        self.n = n if n is not None else (_height(self.vars[0]) if self.vars else (len(self.rownames) if self.rownames else 0))
        self.desc = ''
        self.userdata = np.zeros((0, 0))
        self.units = None
        self.vdescs = None
        self.dims = list(self.DIMS)
        if len(set(self.names)) != len(self.names):
            dup = next(x for x in self.names if self.names.count(x) > 1)
            raise MError('MATLAB:table:DuplicateVarNames', f"Duplicate table variable name: '{dup}'.")
        for v, nm in zip(self.vars, self.names):
            if _height(v) != self.n:
                raise MError('MATLAB:table:UnequalVarLengths', f"All table variables must have the same number of rows: '{nm}' has {_height(v)}, the table {self.n}.")

    # ---- the value-object machinery ---------------------------------------------------------------------------
    @property
    def shape(self):
        return (self.n, len(self.vars))

    def copy_meta(self, vars_, names, rownames, n=None, keep=None):
        """A table with this one's properties and new variables (keep: the
        positions of the variables kept, for their units and descriptions)."""
        o = type(self).__new__(type(self))
        Table.__init__(o, vars_, names, rownames, n)
        o.desc, o.userdata, o.dims = self.desc, self.userdata, list(self.dims)
        if keep is not None:
            o.units = [self.units[k] for k in keep] if self.units else None
            o.vdescs = [self.vdescs[k] for k in keep] if self.vdescs else None
        else:
            o.units, o.vdescs = (list(self.units) if self.units else None), (list(self.vdescs) if self.vdescs else None)
        return o

    def value_copy(self):
        o = self.copy_meta(list(self.vars), list(self.names), self.rownames, self.n)
        return o

    def empty_like(self, shape=(0, 0)):
        return Table([], [], None, 0)

    def row_label(self):
        return self.rownames

    def sub_rows(self, rows):
        """The table of those rows (0-based positions)."""
        rows = np.asarray(rows, int)
        vars_ = [_take_rows(v, rows) for v in self.vars]
        rn = [self.rownames[r] for r in rows] if self.rownames is not None else None
        return self.copy_meta(vars_, self.names, rn, len(rows))

    def sub_vars(self, cols):
        cols = list(cols)
        return self.copy_meta([self.vars[c] for c in cols], [self.names[c] for c in cols], self.rownames, self.n, keep=cols)

    # ---- subscripts --------------------------------------------------------------------------------------
    def row_index(self, a):
        """Row positions (0-based) from a subscript."""
        from ..index import conv
        if a is COLON or (type(a) is Char and a.str() == ':'):
            return np.arange(self.n)
        if type(a) in (Char, Str, Cell):
            names = _texts(a, 'table')
            if self.rownames is None:
                raise MError('MATLAB:table:RowNamesNotPresent' if False else 'MATLAB:table:UnrecognizedRowName', 'This table has no row names to index it by.')
            pos = []
            for nm in names:
                if nm not in self.rownames:
                    raise MError('MATLAB:table:UnrecognizedRowName', f"Unrecognized row name '{nm}'.")
                pos.append(self.rownames.index(nm))
            return np.array(pos, int)
        ix, _, _ = conv(a)
        if ix is COLON:
            return np.arange(self.n)
        ix = np.asarray(ix, int).reshape(-1)
        return ix

    def var_index(self, a, allow_new=False):
        """Variable positions (0-based) from a subscript (names, numbers, a mask, ':')."""
        from ..index import conv
        if a is COLON or (type(a) is Char and a.str() == ':'):
            return list(range(len(self.vars)))
        if type(a) in (Char, Str, Cell):
            names = _texts(a, 'table')
            pos = []
            for nm in names:
                if nm in self.names:
                    pos.append(self.names.index(nm))
                elif allow_new:
                    pos.append(nm)
                else:
                    raise MError('MATLAB:table:UnrecognizedVarName', f"Unrecognized table variable name '{nm}'.")
            return pos
        if type(a) is VARTYPE:
            return [k for k, v in enumerate(self.vars) if a.matches(v)]
        ix, _, _ = conv(a)
        if ix is COLON:
            return list(range(len(self.vars)))
        ix = [int(i) for i in np.asarray(ix).reshape(-1)]
        if ix and max(ix) >= len(self.vars) and not allow_new:
            raise MError('MATLAB:table:VarIndexOutOfRange', f'Variable index exceeds table dimensions: the table has {len(self.vars)} variables.')
        return ix

    def _two(self, args):
        if len(args) != 2:
            raise MError('MATLAB:table:LinearSubscript', 'A table is indexed by two subscripts, rows and variables: T(rows, vars).')
        return args

    def index(self, args):
        r, v = self._two(args)
        rows = self.row_index(r)
        if rows.size and (rows.max() >= self.n or rows.min() < 0):
            raise MError('MATLAB:table:RowIndexOutOfRange', f'Row index exceeds table dimensions: the table has {self.n} rows.')
        cols = self.var_index(v)
        t = self.sub_vars(cols)
        return t.sub_rows(rows) if not (r is COLON) else t

    def brace(self, args):
        r, v = self._two(args)
        sub = self.index(args)
        if not sub.vars:
            return [np.zeros((sub.n, 0))]
        if len(sub.vars) == 1:
            return [sub.vars[0]]
        try:
            return [_cat_cols(sub.vars)]
        except MError:
            raise MError('MATLAB:table:ExtractDataIncompatibleTypeError', 'Unable to put the table variables together into one array: they are of classes that do not concatenate.')

    def index_assign(self, args, V):
        r, v = self._two(args)
        if is_empty_double(V) and not isinstance(V, VObj):
            return self.delete(args)
        rows = self.row_index(r)
        cols = self.var_index(v, allow_new=True)
        T = self.value_copy()
        n_new = max(T.n, int(rows.max()) + 1 if rows.size else 0)
        if isinstance(V, Table):
            if V.n not in (len(rows), 1) or len(V.vars) not in (len(cols), 1):
                raise MError('MATLAB:table:AssignmentDimensionMismatch', 'The table on the right must have as many rows and variables as are assigned.')
            src = [V.vars[k if len(V.vars) > 1 else 0] for k in range(len(cols))]
            reps = len(rows) if V.n == 1 and len(rows) != 1 else None
            if reps:
                src = [_take_rows(s, np.zeros(reps, int)) for s in src]
        elif type(V) is Cell:
            c = V.a
            if c.ndim != 2 or (c.shape != (len(rows), len(cols)) and c.size != len(cols) and c.size != 1):
                raise MError('MATLAB:table:AssignmentDimensionMismatch', 'The cell array on the right must have one element per variable (and row) assigned.')
            if c.shape == (len(rows), len(cols)) and len(rows) > 1:
                src = []
                for k, col in enumerate(cols):
                    elems = list(c[:, k])
                    as_cell = type(T.vars[col]) is Cell if not isinstance(col, str) else any(type(e) in (Char, Cell) for e in elems)
                    src.append(Cell(c[:, k:k + 1].copy()) if as_cell else _cat_rows(elems))
            else:
                flat = c.reshape(-1, order='F')
                src = [flat[k if flat.size > 1 else 0] for k in range(len(cols))]
        else:
            if len(cols) == 1 and _height(V) in (len(rows), 1):
                src = [V]
            else:
                raise MError('MATLAB:table:InvalidRHS', 'The right side of an assignment to a table must be a table or a cell array (or, for one variable, its values).')
        T._grow(n_new)
        for k, c in enumerate(cols):
            s = src[k]
            if isinstance(c, str):
                if not _valid_name(c):
                    raise MError('MATLAB:table:InvalidVarName', f"'{c}' is not a valid variable name.")
                base = _missing_like(s, T.n)
                T.vars.append(base)
                T.names.append(c)
                if T.units:
                    T.units.append('')
                if T.vdescs:
                    T.vdescs.append('')
                c = len(T.vars) - 1
            elif c >= len(T.vars):
                raise MError('MATLAB:table:VarIndexOutOfRange', 'Variables are added to a table by name.')
            T.vars[c] = _assign_rows(T.vars[c], rows, s, T.n)
        return T

    def brace_assign(self, args, V):
        r, v = self._two(args)
        rows = self.row_index(r)
        cols = self.var_index(v)
        T = self.value_copy()
        T._grow(max(T.n, int(rows.max()) + 1 if rows.size else 0))
        if len(cols) == 1:
            T.vars[cols[0]] = _assign_rows(T.vars[cols[0]], rows, V, T.n)
            return T
        from ..index import idx
        widths = [shape_of(T.vars[c])[1] for c in cols]
        if shape_of(V)[1] != sum(widths) and numel(V) != 1:
            raise MError('MATLAB:table:AssignmentDimensionMismatch', 'The right side must have as many columns as the variables assigned.')
        pos = 0
        for c, w in zip(cols, widths):
            part = V if numel(V) == 1 else idx(V, (COLON, out(np.arange(pos + 1, pos + w + 1, dtype=float).reshape(1, -1))))
            T.vars[c] = _assign_rows(T.vars[c], rows, part, T.n)
            pos += w
        return T

    def _grow(self, n_new):
        if n_new > self.n:
            extra = n_new - self.n
            self.vars = [_cat_rows([v, _missing_like(v, extra)]) for v in self.vars]
            if self.rownames is not None:
                self.rownames += [f'Row{self.n + k + 1}' for k in range(extra)]
            self.grow_times(extra)
            self.n = n_new

    def grow_times(self, extra):
        pass

    def delete(self, args):
        r, v = self._two(args)
        all_rows = r is COLON or (type(r) is Char and r.str() == ':')
        all_vars = v is COLON or (type(v) is Char and v.str() == ':')
        if all_rows and not all_vars:
            cols = set(self.var_index(v))
            keep = [k for k in range(len(self.vars)) if k not in cols]
            return self.sub_vars(keep)
        if all_vars or not all_rows:
            if not all_vars:
                raise MError('MATLAB:table:NullAssignment', 'Delete whole rows, T(rows, :) = [], or whole variables, T(:, vars) = [].')
            rows = set(int(x) for x in self.row_index(r))
            keep = [k for k in range(self.n) if k not in rows]
            return self.sub_rows(keep)
        return self.sub_rows([])

    def columns(self):
        return [self.sub_vars([k]) for k in range(len(self.vars))]

    def transposed(self):
        raise MError('MATLAB:table:UndefinedFunction', "Transposing a table is not possible: use rows2vars.")

    @classmethod
    def concat(cls, axis, vals):
        parts = [v for v in vals if not (type(v) is np.ndarray and v.size == 0)]
        if not all(isinstance(p, Table) for p in parts):
            raise MError('MATLAB:table:ConcatenationNotTable', 'Tables concatenate only with tables.')
        first = parts[0]
        if axis == 1:
            names, vars_ = [], []
            for p in parts:
                if p.n != first.n:
                    raise MError('MATLAB:table:horzcat:SizeMismatch', 'All tables being horizontally concatenated must have the same number of rows.')
                for nm, v in zip(p.names, p.vars):
                    if nm in names:
                        raise MError('MATLAB:table:DuplicateVarNames', f"Duplicate table variable name: '{nm}'.")
                    names.append(nm)
                    vars_.append(v)
            return first.copy_meta(vars_, names, first.rownames, first.n)
        for p in parts[1:]:
            if sorted(p.names) != sorted(first.names):
                raise MError('MATLAB:table:vertcat:UnequalVarNames', 'All tables being vertically concatenated must have the same variable names.')
        vars_ = []
        for k, nm in enumerate(first.names):
            vars_.append(_cat_rows([p.vars[p.names.index(nm)] for p in parts]))
        if all(p.rownames is not None for p in parts):
            rn = [x for p in parts for x in p.rownames]
        else:
            rn = None
        res = first.copy_meta(vars_, first.names, rn, sum(p.n for p in parts))
        res.concat_times(parts)
        return res

    def concat_times(self, parts):
        pass

    def binop(self, op, a, b):
        raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for tables: work on their variables (T.Var) or use varfun.")

    def unop(self, op):
        raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for tables.")

    def key(self):
        raise MError('MATLAB:table:UndefinedFunction', 'Tables are compared and sorted by their rows: use sortrows or unique.')

    # ---- properties --------------------------------------------------------------------------------------
    def propnames(self):
        return list(self.names) + ['Properties']

    def properties(self):
        names_cell = Cell.of_list([Char.of(n) for n in self.names], (1, len(self.names)))
        f = {
            'Description': Char.of(self.desc),
            'UserData': self.userdata,
            'DimensionNames': Cell.of_list([Char.of(d) for d in self.dims], (1, 2)),
            'VariableNames': names_cell,
            'VariableDescriptions': Cell.of_list([Char.of(x) for x in (self.vdescs or [''] * len(self.names))], (1, len(self.names))) if self.vdescs else Cell.empty(),
            'VariableUnits': Cell.of_list([Char.of(x) for x in (self.units or [''] * len(self.names))], (1, len(self.names))) if self.units else Cell.empty(),
            'VariableContinuity': np.zeros((0, 0)),
        }
        f.update(self.row_props())
        return Struct.scalar(f)

    def row_props(self):
        return {'RowNames': Cell.of_list([Char.of(x) for x in self.rownames], (len(self.rownames), 1)) if self.rownames else Cell.empty()}

    def getprop(self, name):
        if name == 'Properties':
            return self.properties()
        if name in self.names:
            return self.vars[self.names.index(name)]
        if name == self.dims[0]:
            return self.row_values()
        if name == self.dims[1]:
            return self.brace((COLON, COLON))[0]
        raise MError('MATLAB:table:UnrecognizedVarName', f"Unrecognized table variable name '{name}'.")

    def row_values(self):
        if self.rownames is None:
            raise MError('MATLAB:table:NoRowNames', 'This table has no row names.')
        return Cell.of_list([Char.of(x) for x in self.rownames], (len(self.rownames), 1))

    def setprop(self, name, value):
        if name == 'Properties':
            self.set_properties(value)
            return
        if name == self.dims[0]:
            self.set_rows(value)
            return
        if name in self.names:
            k = self.names.index(name)
            if _height(value) != self.n and not (self.n == 0 and not self.vars):
                raise MError('MATLAB:table:RowDimensionMismatch', f'To assign to a variable, the value must have {self.n} rows.')
            self.vars[k] = share(_var_value(value))
            return
        if not _valid_name(name):
            raise MError('MATLAB:table:InvalidVarName', f"'{name}' is not a valid variable name.")
        if self.vars and _height(value) != self.n:
            if numel(value) == 1:
                value = _take_rows(value if type(value) not in (float, bool, complex) else np.array([[value]]), np.zeros(self.n, int))
            else:
                raise MError('MATLAB:table:RowDimensionMismatch', f'To add a variable, the value must have {self.n} rows.')
        if not self.vars and self.rownames is None:
            self.n = _height(value)
        self.vars.append(share(_var_value(value)))
        self.names.append(name)
        if self.units:
            self.units.append('')
        if self.vdescs:
            self.vdescs.append('')

    def set_rows(self, value):
        if type(value) is np.ndarray and value.size == 0:
            self.rownames = None
            return
        names = _texts(value, 'table')
        if len(names) != self.n:
            raise MError('MATLAB:table:IncorrectNumberOfRowNames', f'The number of row names must be {self.n}.')
        if len(set(names)) != len(names):
            raise MError('MATLAB:table:DuplicateRowNames', 'Row names must be unique.')
        self.rownames = list(names)

    def set_properties(self, s):
        if type(s) is not Struct:
            raise MError('MATLAB:table:InvalidProperties', 'Properties must be set field by field: T.Properties.VariableNames = ...')
        cur = self.properties()
        for k in s.f:
            v = s.get1(k)
            old = cur.get1(k) if k in cur.f else None
            if old is not None and _same_value(old, v):
                continue
            self.set_one(k, v)

    def set_one(self, k, v):
        if k == 'VariableNames':
            names = _texts(v, 'table')
            if len(names) != len(self.vars):
                raise MError('MATLAB:table:IncorrectNumberOfVarNames', f'The number of variable names must be {len(self.vars)}.')
            if len(set(names)) != len(names):
                raise MError('MATLAB:table:DuplicateVarNames', 'Variable names must be unique.')
            self.names = list(names)
        elif k == 'RowNames':
            self.set_rows(v)
        elif k == 'Description':
            self.desc = py_str(v)
        elif k == 'UserData':
            self.userdata = v
        elif k == 'VariableUnits':
            self.units = _texts(v, 'table') if numel(v) else None
        elif k == 'VariableDescriptions':
            self.vdescs = _texts(v, 'table') if numel(v) else None
        elif k == 'DimensionNames':
            d = _texts(v, 'table')
            if len(d) != 2:
                raise MError('MATLAB:table:IncorrectNumberOfDimNames', 'There are two dimension names.')
            self.dims = d
        elif k == 'VariableContinuity':
            pass
        else:
            raise MError('MATLAB:table:UnknownProperty', f"Unrecognized table property '{k}'.")

    # ---- display -------------------------------------------------------------------------------------
    def elem_strings(self):
        return np.array([[f'{self.n}×{len(self.vars)} {self.cls}']], object)

    def summary_text(self, brackets='[]'):
        t = f'{self.n}×{len(self.vars)} {self.cls}'
        return f'[{t}]' if brackets == '[]' else t

    def label_column(self):
        """The leading column: row names (or row times), or None."""
        return (None, [str(x) for x in self.rownames]) if self.rownames is not None else None

    def display_lines(self):
        from ..display import FMT
        loose = FMT['spacing'] == 'loose'
        lines = [f'  {self.n}×{len(self.vars)} {"empty " if self.n == 0 or not self.vars else ""}{self.cls}']
        if self.n == 0 or not self.vars:
            if self.vars:
                lines += ([''] if loose else []) + ['    ' + '    '.join(self.names)]
            return lines
        return lines + ([''] if loose else []) + self.grid_lines()

    def grid_lines(self):
        """The variables side by side under their names: each variable's
        values a block (numbers to the right, text to the left) centred
        under its name; row names (or times) first, unnamed."""
        from ..display import FMT
        cols = []                       # (header, cells, is the label column)
        lab = self.label_column()
        if lab is not None:
            head, cells = lab
            w = max(len(c) for c in cells) if cells else 0
            cols.append((head or '', [c.ljust(w) for c in cells], lab[0] is not None))
        for nm, v in zip(self.names, self.vars):
            cells, align = _var_cells(v, self.n)
            bw = max(len(c) for c in cells) if cells else 0
            cells = [c.ljust(bw) if align == 'left' else c.rjust(bw) for c in cells]
            w = max(bw, len(nm))
            lp = (w - bw) // 2
            cols.append((nm, [' ' * lp + c + ' ' * (w - bw - lp) for c in cells], True))
        widths = [max([len(c) for c in cells] + [len(head)]) for head, cells, named in cols]
        hdr, und = [], []
        for (head, cells, named), w in zip(cols, widths):
            lp = (w - len(head)) // 2
            hdr.append(' ' * lp + head + ' ' * (w - len(head) - lp) if named else ' ' * w)
            und.append('_' * w if named else ' ' * w)
        lines = ['    ' + '    '.join(hdr).rstrip(), '    ' + '    '.join(und).rstrip()]
        if FMT['spacing'] == 'loose':
            lines.append('')
        for i in range(self.n):
            lines.append('    ' + '    '.join(cells[i].ljust(w) for (head, cells, named), w in zip(cols, widths)).rstrip())
        return lines

    def disp_lines(self):
        if self.n == 0 or not self.vars:
            return self.display_lines()[1:]
        return self.grid_lines()


def _same_value(a, b):
    if type(a) is not type(b):
        return False
    if type(a) is Cell:
        return a.a.shape == b.a.shape and all(_same_value(x, y) for x, y in zip(a.a.flat, b.a.flat))
    if type(a) is Char:
        return a.str() == b.str() if a.a.shape[0] <= 1 and b.a.shape[0] <= 1 else np.array_equal(a.a, b.a)
    try:
        return bool(np.array_equal(np.asarray(a), np.asarray(b)))
    except Exception:
        return a is b


def _assign_rows(var, rows, val, n):
    from ..index import asgn
    if type(val) in (float, bool, complex):
        val = np.array([[val]], dtype=bool if type(val) is bool else complex if type(val) is complex else float)
    if type(var) is Cell and type(val) is not Cell:
        # a cell variable holds what is put in it, one element per row
        val = Cell.of_list([val], (1, 1))
    w = shape_of(var)[1] if len(shape_of(var)) > 1 else 1
    r = asgn(var, (_rows_arg(rows), COLON if w == shape_of(val)[1] or numel(val) == 1 else COLON), val)
    return r


def _num_strs(col):
    """A numeric column's cells as the table shows them."""
    col = np.asarray(col)
    if col.dtype == bool:
        return ['true' if x else 'false' for x in col]
    if col.dtype.kind in 'iu':
        return [str(int(x)) for x in col]
    if col.dtype.kind == 'c':
        return [f'{x.real:.4g}{"+" if x.imag >= 0 else "-"}{abs(x.imag):.4g}i' for x in col]
    fin = col[np.isfinite(col)]
    whole = fin.size == 0 or (np.all(fin == np.round(fin)) and np.all(np.abs(fin) < 1e15))
    res = []
    for x in col:
        if np.isnan(x):
            res.append('NaN')
        elif np.isinf(x):
            res.append('Inf' if x > 0 else '-Inf')
        elif whole:
            res.append(str(int(x)))
        else:
            res.append('%.5g' % x)
    return res


def _var_cells(v, n):
    """Each row of a variable as text, and how to align it."""
    from ..display import summary
    t = type(v)
    if isinstance(v, Table):
        return [f'1×{len(v.vars)} table'] * n, 'left'
    if isinstance(v, VObj):
        s = np.asarray(v.elem_strings(), object).reshape(n, -1)
        return ['   '.join(str(x) for x in row) for row in s], 'left' if v.cls == 'categorical' else 'right'
    if t is Cell:
        a = v.a.reshape(n, -1)
        cols = []
        for j in range(a.shape[1]):
            texts = [x.str() for x in a[:, j] if type(x) is Char and x.a.shape[0] <= 1]
            m = max((len(t) for t in texts), default=0)
            col = []
            for x in a[:, j]:
                if type(x) is Char and x.a.shape[0] <= 1:
                    t = x.str()
                    col.append("{'" + t + "'" + ' ' * (m - len(t)) + '}')
                else:
                    col.append('{' + summary(x) + '}')
            w = max(len(c) for c in col) if col else 0
            cols.append([c.ljust(w) for c in col])
        return ['    '.join(c[i] for c in cols) for i in range(n)], 'left'
    if t is Str:
        a = v.a.reshape(n, -1)
        return ['    '.join('<missing>' if s is None else f'"{s}"' for s in row) for row in a], 'left'
    if t is Char:
        rows = v.row_strs() if v.a.shape[0] > 0 else [''] * n
        return [f"'{r}'" for r in rows], 'left'
    if t is Struct:
        return [f'1×1 struct'] * n, 'left'
    a = np.asarray(v)
    if a.ndim == 1:
        a = a.reshape(-1, 1)
    a = a.reshape(n, -1) if a.size else np.zeros((n, 0))
    cols = [_num_strs(a[:, j]) for j in range(a.shape[1])]
    if not cols:
        return [''] * n, 'right'
    widths = [max(len(s) for s in c) for c in cols]
    if a.dtype == bool:
        return ['    '.join(c[i].ljust(w) for c, w in zip(cols, widths)) for i in range(n)], 'left'
    return ['    '.join(c[i].rjust(w) for c, w in zip(cols, widths)) for i in range(n)], 'right'


# ---- timetable ---------------------------------------------------------------------------------------------

class TimeTable(Table):
    cls = 'timetable'
    DIMS = ['Time', 'Variables']

    def __init__(self, vars_, names, times, n=None):
        self.times = times
        Table.__init__(self, vars_, names, None, _height(times) if n is None else n)
        if _height(times) != self.n:
            raise MError('MATLAB:timetable:IncorrectNumberOfRowTimes', 'There must be one row time for each row.')

    def copy_meta(self, vars_, names, rownames, n=None, keep=None):
        o = Table.copy_meta(self, vars_, names, None, n, keep)
        o.times = self.times if n is None or n == self.n else self.times
        return o

    def sub_rows(self, rows):
        rows = np.asarray(rows, int)
        o = Table.sub_rows(self, rows)
        o.times = _take_rows(self.times, rows)
        return o

    def row_index(self, a):
        from .timetypes import DateTime, Duration
        if type(a) in (DateTime, Duration) or (type(a) in (Char, Str, Cell) and not (type(a) is Char and a.str() == ':')):
            want = self.times.coerce(a)
            k = self.times.key().reshape(-1)
            w = want.key().reshape(-1)
            return np.array([i for x in w for i in np.flatnonzero(k == x)], int)
        if type(a) is TIMERANGE:
            k = self.times.key().reshape(-1)
            return np.flatnonzero(a.contains(self.times, k))
        return Table.row_index(self, a)

    def grow_times(self, extra):
        self.times = _cat_rows([self.times, _missing_like(self.times, extra)])

    def concat_times(self, parts):
        self.times = _cat_rows([p.times for p in parts])

    def row_props(self):
        from .timetypes import DateTime, Duration
        t = self.times
        d = {'RowTimes': t}
        k = t.key().reshape(-1)
        d['StartTime'] = _take_rows(t, [0]) if self.n else t
        steps = np.diff(k)
        if steps.size and np.allclose(steps, steps[0]):
            d['SampleRate'] = 1.0 / float(steps[0]) if steps[0] else math.nan
            d['TimeStep'] = Duration(np.array([[float(steps[0])]]))
        else:
            d['SampleRate'] = math.nan
            d['TimeStep'] = Duration(np.array([[np.nan]]))
        return d

    def row_values(self):
        return self.times

    def set_rows(self, value):
        from .timetypes import DateTime, Duration
        if type(value) not in (DateTime, Duration) or _height(value) != self.n:
            raise MError('MATLAB:timetable:InvalidRowTimes', f'The row times must be {self.n} datetimes or durations.')
        self.times = value

    def set_one(self, k, v):
        if k in ('RowTimes',):
            self.set_rows(v)
        elif k in ('StartTime', 'TimeStep', 'SampleRate'):
            raise MError('MATLAB:timetable:ReadOnly', f'{k} is set through the row times here.')
        else:
            Table.set_one(self, k, v)

    def properties(self):
        s = Table.properties(self)
        return s

    def label_column(self):
        s = np.asarray(self.times.elem_strings(), object).reshape(-1)
        return (self.dims[0], [str(x) for x in s])


class _Selector(VObj):
    """vartype and timerange: values that pick a table's variables or a
    timetable's rows, shown by their class name."""
    ARRAYS = ()

    @property
    def shape(self):
        return (1, 1)

    def index(self, args):
        return self

    def elem_strings(self):
        return np.array([[self.cls]], object)

    def display_lines(self):
        return [f'  {self.cls}']

    def disp_lines(self):
        return [f'  {self.cls}']

    def summary_text(self, brackets='[]'):
        return f'[1×1 {self.cls}]' if brackets == '[]' else f'1×1 {self.cls}'


class _VarType(_Selector):
    """vartype('numeric'): selects the variables of a type."""
    cls = 'vartype'

    def __init__(self, kind):
        self.kind = kind.lower()

    def matches(self, v):
        c = class_of(v)
        k = self.kind
        if k == 'numeric':
            return c in ('double', 'single', 'int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32', 'uint64')
        if k == 'cellstr':
            return type(v) is Cell and all(type(x) is Char for x in v.a.flat)
        return c == k


VARTYPE = _VarType


class _TimeRange(_Selector):
    """timerange(a, b): selects the rows of a timetable between two times."""
    cls = 'timerange'

    def __init__(self, a, b, kind='openright'):
        self.a, self.b, self.kind = a, b, kind

    def contains(self, times, k):
        lo = float(times.coerce(self.a).key().reshape(-1)[0])
        hi = float(times.coerce(self.b).key().reshape(-1)[0])
        left = k > lo if self.kind in ('open', 'openleft') else k >= lo
        right = k < hi if self.kind in ('open', 'openright') else k <= hi
        return left & right


TIMERANGE = _TimeRange


# ---- making tables -------------------------------------------------------------------------------------------

def _split_opts(args, names):
    data = list(args)
    argnames = None
    if data and isinstance(data[-1], R.ArgNames):
        argnames = data.pop().names
    opts = {}
    k = 0
    pos = []
    while k < len(data):
        o = opt_str(data[k])
        if o is not None and o.lower() in names and k + 1 < len(data):
            opts[o.lower()] = data[k + 1]
            k += 2
            continue
        pos.append(k)
        k += 1
    return [data[i] for i in pos], opts, ([argnames[i] if argnames and i < len(argnames) else None for i in pos] if argnames else None)


def _var_value(v):
    """A table variable from a value: numbers as columns kept; a row of text one row."""
    if type(v) in (float, bool, complex):
        return np.array([[v]], dtype=bool if type(v) is bool else complex if type(v) is complex else float)
    return v


_TYPES = {'double': lambda n: np.zeros((n, 1)), 'single': lambda n: np.zeros((n, 1), np.float32), 'logical': lambda n: np.zeros((n, 1), bool),
          'cell': lambda n: Cell(_empties(n)), 'cellstr': lambda n: Cell(_chars(n)), 'string': lambda n: Str(np.full((n, 1), None, object)),
          'char': lambda n: Cell(_chars(n))}


def _empties(n):
    c = np.empty((n, 1), object)
    for i in range(n):
        c[i, 0] = np.zeros((0, 0))
    return c


def _chars(n):
    c = np.empty((n, 1), object)
    for i in range(n):
        c[i, 0] = Char.of('')
    return c


def _typed(kind, n):
    from .timetypes import DateTime, Duration, CalDuration
    from .categoricals import Categorical
    k = kind.lower()
    if k in _TYPES:
        return _TYPES[k](n)
    if k in ('int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32', 'uint64'):
        return np.zeros((n, 1), np.dtype(k))
    if k == 'datetime':
        return DateTime(np.full((n, 1), np.nan))
    if k == 'duration':
        return Duration(np.zeros((n, 1)))
    if k == 'calendarduration':
        z = np.zeros((n, 1))
        return CalDuration(z, z, z)
    if k == 'categorical':
        return Categorical(np.zeros((n, 1)), [])
    raise err('MATLAB:table:InvalidVarType', f"'{kind}' is not a variable type table knows.", 'table')


@bi('table', arr=False)
def table(nargout, *args):
    """table(var1, var2, ...): a table of those variables (named after the
    variables given, or Var1, Var2, ...); 'VariableNames', 'RowNames',
    'DimensionNames' as options; table('Size', [n m], 'VariableTypes', types)
    a table of default values."""
    data, opts, argnames = _split_opts(args, ('variablenames', 'rownames', 'size', 'variabletypes', 'dimensionnames', 'variableunits', 'variabledescriptions'))
    if 'size' in opts:
        sz = [int(x) for x in np.asarray(darr(opts['size'])).reshape(-1)]
        if len(sz) != 2 or 'variabletypes' not in opts:
            raise err('MATLAB:table:InvalidSize', "Give 'Size', [rows vars] and 'VariableTypes'.", 'table')
        types = _texts(opts['variabletypes'], 'table')
        if len(types) != sz[1]:
            raise err('MATLAB:table:VariableTypesSizeMismatch', 'Give one variable type for each variable.', 'table')
        vars_ = [_typed(t, sz[0]) for t in types]
        names = _texts(opts['variablenames'], 'table') if 'variablenames' in opts else [f'Var{k + 1}' for k in range(sz[1])]
        T = Table(vars_, names, None, sz[0])
    else:
        vars_ = [_var_value(v) for v in data]
        if 'variablenames' in opts:
            names = _texts(opts['variablenames'], 'table')
            if len(names) != len(vars_):
                raise err('MATLAB:table:IncorrectNumberOfVarNames', 'Give one variable name for each variable.', 'table')
        else:
            names = [(argnames[k] if argnames and argnames[k] else f'Var{k + 1}') for k in range(len(vars_))]
        n = _height(vars_[0]) if vars_ else 0
        rn = None
        if 'rownames' in opts and numel(opts['rownames']):
            rn = _texts(opts['rownames'], 'table')
            if not vars_:
                n = len(rn)
        try:
            T = Table(vars_, names, rn, n)
        except MError as e:
            raise err(e.identifier, e.message, 'table')
    if 'dimensionnames' in opts:
        T.set_one('DimensionNames', opts['dimensionnames'])
    if 'variableunits' in opts:
        T.set_one('VariableUnits', opts['variableunits'])
    if 'variabledescriptions' in opts:
        T.set_one('VariableDescriptions', opts['variabledescriptions'])
    return T


def _times_value(v):
    from .timetypes import DateTime, Duration
    if type(v) not in (DateTime, Duration):
        raise err('MATLAB:timetable:InvalidRowTimes', 'The row times must be datetimes or durations.', 'timetable')
    return v.mapped(lambda a: a.reshape(-1, 1))


@bi('timetable', arr=False)
def timetable(nargout, *args):
    """timetable(rowTimes, var1, var2, ...) or timetable(var1, ..., 'RowTimes',
    rowTimes): a table whose rows are points in time (datetimes or
    durations); timetable(..., 'SampleRate', fs) or 'TimeStep', dt with
    'StartTime', t0: regular row times."""
    from .timetypes import DateTime, Duration
    data, opts, argnames = _split_opts(args, ('variablenames', 'rowtimes', 'samplerate', 'timestep', 'starttime', 'dimensionnames', 'size', 'variabletypes'))
    if 'rowtimes' in opts:
        times = _times_value(opts['rowtimes'])
        vars_ = data
        an = argnames
    elif data and type(data[0]) in (DateTime, Duration):
        times = _times_value(data[0])
        vars_ = data[1:]
        an = argnames[1:] if argnames else None
    else:
        vars_ = data
        an = argnames
        n = _height(vars_[0]) if vars_ else 0
        if 'size' in opts:
            sz = [int(x) for x in np.asarray(darr(opts['size'])).reshape(-1)]
            n = sz[0]
            vars_ = [_typed(t, n) for t in _texts(opts['variabletypes'], 'timetable')]
            an = None
        ts = opts.get('timestep')
        start = opts.get('starttime', Duration(np.zeros((1, 1)), ts.fmt if type(ts) is Duration else 's'))
        if type(start) not in (DateTime, Duration):
            raise err('MATLAB:timetable:InvalidStartTime', 'The start time is a datetime or a duration.', 'timetable')
        if 'samplerate' in opts:
            step = 1.0 / float(num(opts['samplerate']))
        elif 'timestep' in opts:
            ts = opts['timestep']
            step = float(ts.a.reshape(-1)[0]) if type(ts) is Duration else float(num(ts))
        else:
            raise err('MATLAB:timetable:NoRowTimes', "Give the row times first, or 'RowTimes', 'SampleRate' or 'TimeStep'.", 'timetable')
        offs = Duration((np.arange(n) * step).reshape(-1, 1))
        times = start.binop('+', start, offs) if type(start) is DateTime else start.mapped(lambda a: float(a.reshape(-1)[0]) + offs.a)
    vars_ = [_var_value(v) for v in vars_]
    if 'variablenames' in opts:
        names = _texts(opts['variablenames'], 'timetable')
    else:
        names = [(an[k] if an and an[k] else f'Var{k + 1}') for k in range(len(vars_))]
    try:
        T = TimeTable(vars_, names, times)
    except MError as e:
        raise err(e.identifier, e.message, 'timetable')
    if 'dimensionnames' in opts:
        T.set_one('DimensionNames', opts['dimensionnames'])
    return T


@bi('istable', arr=False)
def istable(nargout, *args):
    nargchk(args, 1, 1, 'istable')
    return isinstance(args[0], Table) and not isinstance(args[0], TimeTable)


@bi('istimetable', arr=False)
def istimetable(nargout, *args):
    nargchk(args, 1, 1, 'istimetable')
    return isinstance(args[0], TimeTable)


@bi('istabular', arr=False)
def istabular(nargout, *args):
    nargchk(args, 1, 1, 'istabular')
    return isinstance(args[0], Table)


def _need_args(data, k, fn):
    if len(data) < k:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', fn)


def _tab(v, fn):
    if not isinstance(v, Table):
        raise err(f'MATLAB:{fn}:InvalidInput', 'The input must be a table or a timetable.', fn)
    return v


@bi('height', arr=False)
def height(nargout, *args):
    nargchk(args, 1, 1, 'height')
    return float(shape_of(args[0])[0])


@bi('width', arr=False)
def width(nargout, *args):
    nargchk(args, 1, 1, 'width')
    s = shape_of(args[0])
    return float(s[1] if len(s) > 1 else 1)


@bi('vartype', arr=False)
def vartype(nargout, *args):
    """vartype(type): picks a table's variables of a type ('numeric', 'cellstr', or a class) in T(:, vartype(...))."""
    nargchk(args, 1, 1, 'vartype')
    return _VarType(sval(args[0], 'type', 'vartype'))


@bi('timerange', arr=False)
def timerange(nargout, *args):
    """timerange(start, end[, intervalType]): picks the rows of a timetable
    whose times are from start up to (not including) end; 'closed', 'open',
    'openleft', 'openright'."""
    nargchk(args, 2, 3, 'timerange')
    kind = sval(args[2], 'interval type', 'timerange').lower() if len(args) > 2 else 'openright'
    if kind not in ('closed', 'open', 'openleft', 'openright'):
        raise err('MATLAB:timerange:InvalidIntervalType', "The interval type is 'closed', 'open', 'openleft' or 'openright'.", 'timerange')
    return _TimeRange(args[0], args[1], kind)


@bi('head', arr=False)
def head(nargout, *args):
    """The first k rows (8) of a table, or of an array."""
    nargchk(args, 1, 2, 'head')
    k = ival(args[1]) if len(args) > 1 else 8
    v = args[0]
    n = shape_of(v)[0]
    rows = np.arange(min(k, n))
    if isinstance(v, Table):
        return v.sub_rows(rows)
    return _take_rows(v, rows)


@bi('tail', arr=False)
def tail(nargout, *args):
    """The last k rows (8) of a table, or of an array."""
    nargchk(args, 1, 2, 'tail')
    k = ival(args[1]) if len(args) > 1 else 8
    v = args[0]
    n = shape_of(v)[0]
    rows = np.arange(max(n - k, 0), n)
    if isinstance(v, Table):
        return v.sub_rows(rows)
    return _take_rows(v, rows)


@bi('table2array', arr=False)
def table2array(nargout, *args):
    nargchk(args, 1, 1, 'table2array')
    T = _tab(args[0], 'table2array')
    return T.brace((COLON, COLON))[0]


@bi('table2cell', arr=False)
def table2cell(nargout, *args):
    nargchk(args, 1, 1, 'table2cell')
    T = _tab(args[0], 'table2cell')
    c = np.empty((T.n, len(T.vars)), object)
    for j, v in enumerate(T.vars):
        for i in range(T.n):
            x = _take_rows(v, [i])
            if type(x) is Cell and x.a.size == 1:
                x = x.a.flat[0]
            elif type(x) is np.ndarray and x.size == 1:
                x = x.reshape(-1)[0].item() if x.dtype.kind in 'fcb' and x.dtype.itemsize in (1, 8, 16) else x
            c[i, j] = share(x)
    return Cell(c)


@bi('table2struct', arr=False)
def table2struct(nargout, *args):
    """table2struct(T): a struct array, one element per row; with 'ToScalar',
    true a scalar struct whose fields are the variables."""
    nargchk(args, 1, 3, 'table2struct')
    T = _tab(args[0], 'table2struct')
    scalar = len(args) == 3 and bool(num(args[2]))
    if scalar:
        return Struct.scalar({nm: v for nm, v in zip(T.names, T.vars)})
    c = table2cell(1, T)
    f = {nm: np.empty((T.n, 1), object) for nm in T.names}
    for i in range(T.n):
        for j, nm in enumerate(T.names):
            f[nm][i, 0] = c.a[i, j]
    return Struct((T.n, 1), f)


@bi('struct2table', arr=False)
def struct2table(nargout, *args):
    """struct2table(S): a struct array's fields as variables, one row per
    element; a scalar struct's fields as variables of their own rows."""
    data, opts, _ = _split_opts(args, ('asarray', 'rownames'))
    _need_args(data, 1, 'struct2table')
    S = data[0]
    if type(S) is not Struct:
        raise err('MATLAB:struct2table:InvalidInput', 'The input must be a struct.', 'struct2table')
    names = list(S.f)
    if S.size == 1:
        vars_ = [_var_value(S.get1(k)) for k in names]
    else:
        vars_ = [_cat_rows([_cell_elem(x) for x in S.f[k].reshape(-1, order='F')]) for k in names]
    rn = _texts(opts['rownames'], 'struct2table') if 'rownames' in opts else None
    return Table(vars_, names, rn)


def _cell_elem(x):
    """An element of a cell (or a struct field) as one row of a variable: text stays in a cell."""
    if type(x) is Char and x.a.shape[0] <= 1:
        return Cell.of_list([x], (1, 1))
    if type(x) in (float, bool, complex):
        return np.array([[x]], dtype=bool if type(x) is bool else complex if type(x) is complex else float)
    if type(x) is np.ndarray and x.size != 1:
        return Cell.of_list([x], (1, 1))
    return x


@bi('cell2table', arr=False)
def cell2table(nargout, *args):
    """cell2table(C): each column of the cell array a variable (numbers put
    together, text kept as a cell array)."""
    data, opts, _ = _split_opts(args, ('variablenames', 'rownames'))
    _need_args(data, 1, 'cell2table')
    C = data[0]
    if type(C) is not Cell or C.a.ndim != 2:
        raise err('MATLAB:cell2table:InvalidInput', 'The input must be a 2-D cell array.', 'cell2table')
    vars_ = []
    for j in range(C.a.shape[1]):
        col = list(C.a[:, j])
        if col and all(type(x) in (float, bool) or (type(x) is np.ndarray and x.size == 1 and x.dtype.kind in 'fbiu') for x in col):
            kinds = {type(x) if type(x) is not np.ndarray else x.dtype.kind for x in col}
            vars_.append(np.array([float(x) if type(x) is not np.ndarray else x.reshape(-1)[0] for x in col]).reshape(-1, 1).astype(bool if kinds <= {bool, 'b'} else float))
        elif col and all(isinstance(x, VObj) and numel(x) == 1 for x in col) and len({type(x) for x in col}) == 1:
            vars_.append(_cat_rows(col))
        else:
            vars_.append(Cell(C.a[:, j:j + 1].copy()))
    names = _texts(opts['variablenames'], 'cell2table') if 'variablenames' in opts else [f'Var{k + 1}' for k in range(len(vars_))]
    rn = _texts(opts['rownames'], 'cell2table') if 'rownames' in opts else None
    return Table(vars_, names, rn, C.a.shape[0])


@bi('array2table', arr=False)
def array2table(nargout, *args):
    """array2table(A): each column of the matrix a variable."""
    data, opts, _ = _split_opts(args, ('variablenames', 'rownames'))
    _need_args(data, 1, 'array2table')
    A = data[0]
    s = shape_of(A)
    if len(s) != 2:
        raise err('MATLAB:array2table:NDArray', 'The input must be a matrix.', 'array2table')
    from ..index import idx
    vars_ = [idx(A, (COLON, float(j + 1))) for j in range(s[1])]
    vars_ = [_var_value(v) for v in vars_]
    names = _texts(opts['variablenames'], 'array2table') if 'variablenames' in opts else [f'A{k + 1}' if False else f'Var{k + 1}' for k in range(s[1])]
    rn = _texts(opts['rownames'], 'array2table') if 'rownames' in opts else None
    return Table(vars_, names, rn, s[0])


@bi('table2timetable', arr=False)
def table2timetable(nargout, *args):
    """table2timetable(T): the first datetime (or duration) variable as the
    row times; 'RowTimes', a variable name or the times themselves."""
    from .timetypes import DateTime, Duration
    data, opts, _ = _split_opts(args, ('rowtimes',))
    _need_args(data, 1, 'table2timetable')
    T = _tab(data[0], 'table2timetable')
    if 'rowtimes' in opts:
        rt = opts['rowtimes']
        if type(rt) in (DateTime, Duration):
            return _with_times(T, rt, list(range(len(T.vars))))
        k = T.var_index(rt)[0]
    else:
        k = next((i for i, v in enumerate(T.vars) if type(v) in (DateTime, Duration)), None)
        if k is None:
            raise err('MATLAB:table2timetable:NoTimeVariable', 'The table has no datetime or duration variable to take the row times from.', 'table2timetable')
    keep = [i for i in range(len(T.vars)) if i != k]
    tt = _with_times(T, T.vars[k], keep)
    tt.dims = [T.names[k], 'Variables']
    return tt


def _with_times(T, times, keep):
    tt = TimeTable([T.vars[i] for i in keep], [T.names[i] for i in keep], times.mapped(lambda a: a.reshape(-1, 1)))
    tt.desc = T.desc
    return tt


@bi('timetable2table', arr=False)
def timetable2table(nargout, *args):
    nargchk(args, 1, 3, 'timetable2table')
    T = args[0]
    if not isinstance(T, TimeTable):
        raise err('MATLAB:timetable2table:InvalidInput', 'The input must be a timetable.', 'timetable2table')
    out_ = Table([T.times] + list(T.vars), [T.dims[0]] + list(T.names), None, T.n)
    out_.desc = T.desc
    return out_


# ---- the table's variables ----------------------------------------------------------------------------------

def _place(T, where_args):
    """The position new variables go to: 'Before' or 'After' a variable (the end by default)."""
    _, opts, _ = _split_opts(where_args, ('before', 'after', 'newvariablenames'))
    if 'before' in opts:
        return T.var_index(opts['before'])[0], opts
    if 'after' in opts:
        return T.var_index(opts['after'])[0] + 1, opts
    return len(T.vars), opts


@bi('addvars', arr=False)
def addvars(nargout, *args):
    """addvars(T, var1, ..., 'Before' or 'After', var, 'NewVariableNames', names)."""
    data, opts, argnames = _split_opts(args, ('before', 'after', 'newvariablenames'))
    _need_args(data, 1, 'addvars')
    T = _tab(data[0], 'addvars').value_copy()
    new = [_var_value(v) for v in data[1:]]
    pos = T.var_index(opts['before'])[0] if 'before' in opts else (T.var_index(opts['after'])[0] + 1 if 'after' in opts else len(T.vars))
    names = _texts(opts['newvariablenames'], 'addvars') if 'newvariablenames' in opts else [f'Var{len(T.vars) + k + 1}' for k in range(len(new))]
    if len(names) != len(new):
        raise err('MATLAB:addvars:IncorrectNumberOfVarNames', 'Give one name for each new variable.', 'addvars')
    for v in new:
        if _height(v) != T.n:
            raise err('MATLAB:table:RowDimensionMismatch', f'New variables must have {T.n} rows.', 'addvars')
    vars_ = T.vars[:pos] + new + T.vars[pos:]
    nms = T.names[:pos] + names + T.names[pos:]
    return T.copy_meta(vars_, nms, T.rownames, T.n)


@bi('removevars', arr=False)
def removevars(nargout, *args):
    nargchk(args, 2, 2, 'removevars')
    T = _tab(args[0], 'removevars')
    drop = set(T.var_index(args[1]))
    return T.sub_vars([k for k in range(len(T.vars)) if k not in drop])


@bi('movevars', arr=False)
def movevars(nargout, *args):
    """movevars(T, vars, 'Before' or 'After', var)."""
    nargchk(args, 2, 4, 'movevars')
    T = _tab(args[0], 'movevars')
    mv = T.var_index(args[1])
    rest = [k for k in range(len(T.vars)) if k not in mv]
    if len(args) == 4:
        where = sval(args[2], 'Before or After', 'movevars').lower()
        ref = T.var_index(args[3])[0]
        if ref in mv:
            raise err('MATLAB:movevars:InvalidLocation', 'The variable to move next to must not be one being moved.', 'movevars')
        pos = rest.index(ref) + (1 if where == 'after' else 0)
    else:
        pos = len(rest)
    order = rest[:pos] + mv + rest[pos:]
    return T.sub_vars(order)


@bi('renamevars', arr=False)
def renamevars(nargout, *args):
    nargchk(args, 3, 3, 'renamevars')
    T = _tab(args[0], 'renamevars').value_copy()
    old = T.var_index(args[1])
    new = _texts(args[2], 'renamevars')
    if len(old) != len(new):
        raise err('MATLAB:renamevars:SizeMismatch', 'Give one new name for each variable renamed.', 'renamevars')
    names = list(T.names)
    for k, n in zip(old, new):
        names[k] = n
    T.set_one('VariableNames', Cell.of_list([Char.of(n) for n in names], (1, len(names))))
    return T


@bi('splitvars', arr=False)
def splitvars(nargout, *args):
    """splitvars(T): each variable of several columns (or a nested table) made one variable per column."""
    nargchk(args, 1, 4, 'splitvars')
    T = _tab(args[0], 'splitvars')
    which = T.var_index(args[1]) if len(args) > 1 and opt_str(args[1]) != 'NewVariableNames' else list(range(len(T.vars)))
    from ..index import idx
    vars_, names = [], []
    for k, (nm, v) in enumerate(zip(T.names, T.vars)):
        if k in which and isinstance(v, Table):
            vars_ += v.vars
            names += [f'{nm}_{x}' for x in v.names]
        elif k in which and len(shape_of(v)) > 1 and shape_of(v)[1] > 1:
            w = shape_of(v)[1]
            vars_ += [idx(v, (COLON, float(j + 1))) for j in range(w)]
            names += [f'{nm}_{j + 1}' for j in range(w)]
        else:
            vars_.append(v)
            names.append(nm)
    return T.copy_meta([_var_value(v) for v in vars_], names, T.rownames, T.n)


@bi('mergevars', arr=False)
def mergevars(nargout, *args):
    """mergevars(T, vars): the variables put together as one (named Var1
    unless 'NewVariableName' gives a name), where the first of them stood."""
    data, opts, _ = _split_opts(args, ('newvariablename', 'mergeasTable'.lower()))
    _need_args(data, 2, 'mergevars')
    T = _tab(data[0], 'mergevars')
    ks = T.var_index(data[1])
    if not ks:
        raise err('MATLAB:mergevars:NoVariables', 'Give the variables to merge.', 'mergevars')
    name = sval(opts['newvariablename'], 'name', 'mergevars') if 'newvariablename' in opts else 'Var1'
    merged = _cat_cols([T.vars[k] for k in ks])
    first = min(ks)
    vars_, names = [], []
    for k in range(len(T.vars)):
        if k == first:
            vars_.append(merged)
            names.append(name)
        elif k not in ks:
            vars_.append(T.vars[k])
            names.append(T.names[k])
    return T.copy_meta(vars_, names, T.rownames, T.n)


@bi('rows2vars', arr=False)
def rows2vars(nargout, *args):
    """rows2vars(T): the table turned so that its rows are variables (named
    after the row names, or Var1, ...) and its variables rows, their names in
    the first variable, OriginalVariableNames."""
    nargchk(args, 1, 3, 'rows2vars')
    T = _tab(args[0], 'rows2vars')
    names = list(T.rownames) if T.rownames else [f'Var{i + 1}' for i in range(T.n)]
    c = table2cell(1, T)
    vars_ = [Cell.of_list([Char.of(n) for n in T.names], (len(T.names), 1))]
    for i in range(T.n):
        col = [c.a[i, j] for j in range(len(T.vars))]
        if all(type(x) in (float, bool) for x in col):
            vars_.append(np.array([float(x) for x in col]).reshape(-1, 1))
        else:
            vars_.append(Cell(np.array(col, object).reshape(-1, 1)))
    return Table(vars_, ['OriginalVariableNames'] + names, None, len(T.names))


@bi('convertvars', aw=True, arr=False)
async def convertvars(nargout, *args):
    """convertvars(T, vars, type): the variables converted to a type ('double',
    'string', 'categorical', 'cellstr', 'datetime', ...) or by a function."""
    nargchk(args, 3, 3, 'convertvars')
    T = _tab(args[0], 'convertvars').value_copy()
    ks = T.var_index(args[1])
    conv = args[2]
    for k in ks:
        v = T.vars[k]
        if isinstance(conv, FH):
            r = await conv.acall(1, v)
            T.vars[k] = share(_var_value(r[0] if isinstance(r, tuple) else r))
        else:
            kind = sval(conv, 'type', 'convertvars')
            if kind not in _CONVERTS:
                raise err('MATLAB:convertvars:InvalidType', f"'{kind}' is not a type convertvars knows.", 'convertvars')
            T.vars[k] = share(_var_value(await R.call(None, kind, 1, (v,))))
    return T


# ---- order and comparison by rows --------------------------------------------------------------------------

def _row_keys(v, n):
    """Each row of a variable as a tuple that sorts as the language sorts it."""
    from .categoricals import Categorical
    if isinstance(v, VObj):
        k = v.key().reshape(n, -1)
        return [tuple((1, 0.0) if np.isnan(x) else (0, float(x)) for x in row) for row in k]
    t = type(v)
    if t is Cell:
        a = v.a.reshape(n, -1)
        return [tuple((0, x.str()) if type(x) is Char else (0, py_str(x)) if type(x) is Str else (0, float(np.asarray(x).reshape(-1)[0]) if numel(x) else 0.0) for x in row) for row in a]
    if t is Str:
        a = v.a.reshape(n, -1)
        return [tuple((1, '') if s is None else (0, s) for s in row) for row in a]
    if t is Char:
        return [((0, r),) for r in v.row_strs()]
    a = np.asarray(v).reshape(n, -1)
    if a.dtype.kind == 'c':
        return [tuple((1, 0.0) if np.isnan(x) else (0, abs(x), np.angle(x)) for x in row) for row in a]
    return [tuple((1, 0.0) if np.isnan(float(x)) else (0, float(x)) for x in row) for row in a.astype(float)]


def _sorted_rows(T, keys_spec):
    """Row order for (variable positions, descending flags)."""
    order = list(range(T.n))
    for k, desc in reversed(keys_spec):
        if k == 'rownames':
            keys = [((0, r),) for r in (T.rownames or [''] * T.n)]
        elif k == 'rowtimes':
            keys = _row_keys(T.times, T.n)
        else:
            keys = _row_keys(T.vars[k], T.n)
        if desc:
            # missing values first going down, as sort does
            def kf(i, keys=keys):
                return tuple((-m, _neg(x)) for m, x in keys[i])
        else:
            def kf(i, keys=keys):
                return keys[i]
        order.sort(key=kf)
    return order


def _neg(x):
    if isinstance(x, str):
        return tuple(-ord(c) for c in x) + (1,)
    return -x


def _sortrows(nargout, args):
    T = args[0]
    if not isinstance(T, Table):
        return NotImplemented
    vars_spec = None
    dirs = None
    rest = list(args[1:])
    if rest and not (opt_str(rest[0]) is not None and opt_str(rest[0]).lower() in ('ascend', 'descend')):
        vs = rest.pop(0)
        if type(vs) in (Char, Str, Cell):
            nm = _texts(vs, 'sortrows')
            vars_spec = []
            for x in nm:
                if x in (T.dims[0], 'RowNames'):
                    vars_spec.append('rownames' if not isinstance(T, TimeTable) else 'rowtimes')
                else:
                    vars_spec += T.var_index(Char.of(x))
        else:
            nums = np.asarray(darr(vs), float).reshape(-1)
            if np.any(nums != np.round(nums)) or np.any(nums == 0) or np.any(np.abs(nums) > len(T.vars)):
                raise err('MATLAB:table:sortrows:BadVarIndex', f'The variables to sort by are numbers from 1 to {len(T.vars)} (negative for descending).', 'sortrows')
            vars_spec = [int(abs(x)) - 1 for x in nums]
            dirs = [bool(x < 0) for x in nums]
    if rest:
        d = rest.pop(0)
        dl = [x.lower() for x in _texts(d, 'sortrows')]
        if any(x not in ('ascend', 'descend') for x in dl):
            raise err('MATLAB:table:sortrows:BadSortDirection', "The direction is 'ascend' or 'descend'.", 'sortrows')
        n_spec = len(vars_spec) if vars_spec is not None else len(T.vars)
        if len(dl) not in (1, n_spec):
            raise err('MATLAB:table:sortrows:BadSortDirection', 'Give one direction, or one for each variable sorted by.', 'sortrows')
        dirs = [x == 'descend' for x in dl] * (n_spec if len(dl) == 1 else 1)
    if vars_spec is None:
        vars_spec = list(range(len(T.vars))) if not isinstance(T, TimeTable) else ['rowtimes']
    if dirs is None:
        dirs = [False] * len(vars_spec)
    order = _sorted_rows(T, list(zip(vars_spec, dirs)))
    r = T.sub_rows(order)
    return (r, out((np.array(order, float) + 1).reshape(-1, 1))) if nargout > 1 else r


def _unique(nargout, args):
    T = args[0]
    if not isinstance(T, Table):
        return NotImplemented
    keys = [tuple(k for v in T.vars for k in _row_keys(v, T.n)[i]) for i in range(T.n)]
    stable = any((opt_str(a) or '').lower() == 'stable' for a in args[1:])
    seen = {}
    firsts = []
    inv = []
    for i, k in enumerate(keys):
        if k not in seen:
            seen[k] = len(firsts)
            firsts.append(i)
        inv.append(seen[k])
    if not stable:
        order = sorted(range(len(firsts)), key=lambda j: keys[firsts[j]])
        firsts = [firsts[j] for j in order]
        remap = {j: p for p, j in enumerate(order)}
        inv = [remap[g] for g in inv]
    r = T.sub_rows(firsts)
    if nargout <= 1:
        return r
    return r, out((np.array(firsts, float) + 1).reshape(-1, 1)), out((np.array(inv, float) + 1).reshape(-1, 1))


def _isequal_by(name):
    def fn(nargout, args):
        a = args[0]
        if not isinstance(a, Table):
            return False
        for b in args[1:]:
            if not isinstance(b, Table) or type(a) is not type(b) or a.names != b.names or a.n != b.n:
                return False
            if isinstance(a, TimeTable) and not R.BUILTINS[name].fn(1, a.times, b.times):
                return False
            for x, y in zip(a.vars, b.vars):
                if not R.BUILTINS[name].fn(1, x, y):
                    return False
        return True
    return fn


def _ismember(nargout, args):
    """ismember(A, B) of two tables: which rows of A are rows of B, and where."""
    _need_args(args, 2, 'ismember')
    A, B = args[0], args[1]
    if not (isinstance(A, Table) and isinstance(B, Table)):
        raise MError('MATLAB:table:ismember:TypeMismatch', 'ismember compares a table with a table.')
    if sorted(A.names) != sorted(B.names):
        raise MError('MATLAB:table:ismember:DifferentVars', 'The tables must have the same variables.')
    B = B.sub_vars([B.names.index(n) for n in A.names])
    bk = {}
    for i, k in enumerate(_keys_of(B, range(len(B.vars)))):
        bk.setdefault(k, i)
    loc = [bk.get(k, -1) for k in _keys_of(A, range(len(A.vars)))]
    tf = out(np.array([x >= 0 for x in loc]).reshape(-1, 1))
    return (tf, out(np.array(loc, float).reshape(-1, 1) + 1)) if nargout > 1 else tf


def _not_for_tables(name):
    def fn(nargout, args):
        raise MError('MATLAB:table:UndefinedFunction', f"{name} is not defined for tables: apply it to the variables (T.Var, varfun) or use sortrows, unique, rows2vars.")
    return fn


_CONVERTS = ('cellstr', 'string', 'categorical', 'double', 'single', 'logical', 'datetime', 'duration', 'char',
             'int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32', 'uint64')

Table.FUNCS = {name: _not_for_tables(name) for name in ('reshape', 'repmat', 'fliplr', 'flipud', 'flip', 'circshift', 'permute',
                                                         'ipermute', 'squeeze', 'transpose', 'ctranspose', 'rot90', 'sort',
                                                         'issorted', 'min', 'max')}
Table.FUNCS.update({'sortrows': _sortrows, 'unique': _unique, 'isequal': _isequal_by('isequal'),
                    'isequaln': _isequal_by('isequaln'), 'ismember': _ismember})


# ---- grouping and applying functions ------------------------------------------------------------------------

def _groups(T, gvars):
    """Group numbers (0-based) of each row by the grouping variables, the groups in sorted order, and each group's first row."""
    keys = [tuple(k for g in gvars for k in _row_keys(T.vars[g], T.n)[i]) for i in range(T.n)]
    uniq = sorted(set(keys))
    pos = {k: i for i, k in enumerate(uniq)}
    gid = [pos[k] for k in keys]
    first = [gid.index(g) for g in range(len(uniq))]
    return np.array(gid), first


def _fn_name(f):
    if isinstance(f, R.Anon):
        return 'Fun'
    n = getattr(f, 'name', None)
    n = n() if callable(n) else n
    return n if isinstance(n, str) else 'Fun'


async def _call(f, *vals):
    r = await f.acall(1, *vals)
    return r[0] if isinstance(r, tuple) else r


@bi('varfun', aw=True, arr=False)
async def varfun(nargout, *args):
    """varfun(fun, T): fun applied to each variable; 'InputVariables',
    'GroupingVariables' (then once per group, with GroupCount),
    'OutputFormat' ('table', 'uniform', 'cell')."""
    data, opts, _ = _split_opts(args, ('inputvariables', 'groupingvariables', 'outputformat', 'erroroutput'))
    _need_args(data, 2, 'varfun')
    f, T = data[0], _tab(data[1], 'varfun')
    if not isinstance(f, FH):
        raise err('MATLAB:varfun:InvalidFunction', 'The first input must be a function handle.', 'varfun')
    ins = T.var_index(opts['inputvariables']) if 'inputvariables' in opts else list(range(len(T.vars)))
    groups = T.var_index(opts['groupingvariables']) if 'groupingvariables' in opts else []
    ins = [k for k in ins if k not in groups]
    fmt = sval(opts['outputformat'], 'OutputFormat', 'varfun').lower() if 'outputformat' in opts else 'table'
    fname = _fn_name(f)
    if not groups:
        res = [await _call(f, T.vars[k]) for k in ins]
        if fmt == 'uniform':
            return out(np.array([float(num(r)) for r in res]).reshape(1, -1))
        if fmt == 'cell':
            return Cell.of_list(res, (1, len(res)))
        return Table([_var_value(r) for r in res], [f'{fname}_{T.names[k]}' for k in ins], None, _height(_var_value(res[0])) if res else 1)
    gid, first = _groups(T, groups)
    ng = len(first)
    cols = []
    for k in ins:
        vals = [await _call(f, _take_rows(T.vars[k], np.flatnonzero(gid == g))) for g in range(ng)]
        cols.append(vals)
    if fmt == 'uniform':
        return out(np.array([[float(num(v)) for v in c] for c in cols]).T)
    if fmt == 'cell':
        c = np.empty((ng, len(ins)), object)
        for j, vals in enumerate(cols):
            for g, v in enumerate(vals):
                c[g, j] = v
        return Cell(c)
    gvars = [_take_rows(T.vars[g], first) for g in groups]
    counts = out(np.array([np.sum(gid == g) for g in range(ng)], float).reshape(-1, 1))
    vars_ = gvars + [counts] + [_cat_rows([_var_value(v) for v in vals]) for vals in cols]
    names = [T.names[g] for g in groups] + ['GroupCount'] + [f'{fname}_{T.names[k]}' for k in ins]
    return Table(vars_, names, None, ng)


@bi('rowfun', aw=True, nout=99, arr=False)
async def rowfun(nargout, *args):
    """rowfun(fun, T): fun applied to each row, the variables as its inputs;
    'InputVariables', 'GroupingVariables' (then once per group),
    'OutputVariableNames', 'NumOutputs', 'OutputFormat' ('table', 'uniform',
    'cell')."""
    data, opts, _ = _split_opts(args, ('inputvariables', 'groupingvariables', 'outputformat', 'outputvariablenames', 'numoutputs', 'separateinputs', 'erroroutput'))
    _need_args(data, 2, 'rowfun')
    f, T = data[0], _tab(data[1], 'rowfun')
    if not isinstance(f, FH):
        raise err('MATLAB:rowfun:InvalidFunction', 'The first input must be a function handle.', 'rowfun')
    ins = T.var_index(opts['inputvariables']) if 'inputvariables' in opts else list(range(len(T.vars)))
    groups = T.var_index(opts['groupingvariables']) if 'groupingvariables' in opts else []
    ins = [k for k in ins if k not in groups]
    nout = int(num(opts['numoutputs'])) if 'numoutputs' in opts else (len(_texts(opts['outputvariablenames'], 'rowfun')) if 'outputvariablenames' in opts else 1)
    fmt = sval(opts['outputformat'], 'OutputFormat', 'rowfun').lower() if 'outputformat' in opts else 'table'
    names = _texts(opts['outputvariablenames'], 'rowfun') if 'outputvariablenames' in opts else [f'Var{k + 1}' for k in range(nout)]

    async def apply(rows):
        vals = [_take_rows(T.vars[k], rows) for k in ins]
        vals = [v.a.reshape(-1)[0] if type(v) is Cell and v.a.size == 1 else (v.reshape(-1)[0].item() if type(v) is np.ndarray and v.size == 1 and v.dtype.kind in 'fb' else v) for v in vals] if len(rows) == 1 else vals
        r = await f.acall(nout, *vals)
        return list(r) if isinstance(r, tuple) else [r]
    if groups:
        gid, first = _groups(T, groups)
        sets = [np.flatnonzero(gid == g) for g in range(len(first))]
    else:
        sets = [np.array([i]) for i in range(T.n)]
    results = [await apply(s) for s in sets]
    if fmt == 'uniform':
        cols = [out(np.array([float(num(r[j])) for r in results]).reshape(-1, 1)) for j in range(nout)]
        return tuple(cols) if nargout > 1 else cols[0]
    if fmt == 'cell':
        c = np.empty((len(results), nout), object)
        for i, r in enumerate(results):
            for j in range(nout):
                c[i, j] = r[j]
        return Cell(c)
    vars_ = [_cat_rows([_cell_elem(r[j]) for r in results]) for j in range(nout)]
    if groups:
        gvars = [_take_rows(T.vars[g], first) for g in groups]
        counts = out(np.array([len(s) for s in sets], float).reshape(-1, 1))
        return Table(gvars + [counts] + vars_, [T.names[g] for g in groups] + ['GroupCount'] + names, None, len(sets))
    return Table(vars_, names, T.rownames, len(sets))


_METHODS = {'mean': np.nanmean, 'sum': np.nansum, 'min': np.nanmin, 'max': np.nanmax, 'median': np.nanmedian,
            'std': lambda x: np.nanstd(x, ddof=1) if np.sum(np.isfinite(x)) > 1 else (0.0 if np.sum(np.isfinite(x)) == 1 else np.nan),
            'var': lambda x: np.nanvar(x, ddof=1) if np.sum(np.isfinite(x)) > 1 else (0.0 if np.sum(np.isfinite(x)) == 1 else np.nan),
            'range': lambda x: np.nanmax(x) - np.nanmin(x), 'nnz': lambda x: float(np.count_nonzero(x[np.isfinite(x)])),
            'numel': lambda x: float(x.size), 'nummissing': lambda x: float(np.sum(np.isnan(x))),
            'mode': lambda x: float(_mode(x))}


def _mode(x):
    x = x[np.isfinite(x)]
    if not x.size:
        return np.nan
    vals, counts = np.unique(x, return_counts=True)
    return vals[np.argmax(counts)]


@bi('groupsummary', aw=True, arr=False)
async def groupsummary(nargout, *args):
    """groupsummary(T, groupvars, method, datavars): per group of the
    grouping variables, GroupCount and each method ('mean', 'sum', 'min',
    'max', 'median', 'std', 'var', 'range', 'mode', 'nnz', 'numel',
    'nummissing', 'all', or a function) of each data variable (by default
    every numeric variable not grouping); missing values left out."""
    nargchk(args, 2, 6, 'groupsummary')
    T = _tab(args[0], 'groupsummary')
    groups = T.var_index(args[1])
    methods = []
    datavars = None
    if len(args) > 2:
        m = args[2]
        if isinstance(m, FH):
            methods = [m]
        elif type(m) is Cell and any(isinstance(x, FH) for x in m.a.flat):
            methods = [x if isinstance(x, FH) else py_str(x).lower() for x in m.a.reshape(-1, order='F')]
        else:
            methods = [x.lower() for x in _texts(m, 'groupsummary')]
        if methods == ['all']:
            methods = ['mean', 'sum', 'min', 'max', 'range', 'median', 'mode', 'var', 'std', 'nummissing', 'nnz']
        for x in methods:
            if not isinstance(x, FH) and x not in _METHODS:
                raise err('MATLAB:groupsummary:InvalidMethod', f"'{x}' is not a method groupsummary knows.", 'groupsummary')
    if len(args) > 3:
        datavars = T.var_index(args[3])
    elif methods:
        datavars = [k for k, v in enumerate(T.vars) if k not in groups and class_of(v) in ('double', 'single', 'logical', 'int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32', 'uint64')]
    gid, first = _groups(T, groups)
    ng = len(first)
    vars_ = [_take_rows(T.vars[g], first) for g in groups]
    names = [T.names[g] for g in groups]
    vars_.append(out(np.array([np.sum(gid == g) for g in range(ng)], float).reshape(-1, 1)))
    names.append('GroupCount')
    fnum = {}
    for m in methods:
        if isinstance(m, FH):
            fnum[id(m)] = len(fnum) + 1
    for k in (datavars or []):
        col = np.asarray(darr(T.vars[k]), float).reshape(T.n, -1)[:, 0]
        for m in methods:
            if isinstance(m, FH):
                vals = [float(num(await _call(m, out(col[gid == g].reshape(-1, 1))))) for g in range(ng)]
                mname = f'fun{fnum[id(m)]}'
            else:
                with np.errstate(all='ignore'):
                    vals = [float(_METHODS[m](col[gid == g])) if np.any(gid == g) else np.nan for g in range(ng)]
                mname = m
            vars_.append(out(np.array(vals).reshape(-1, 1)))
            names.append(f'{mname}_{T.names[k]}')
    return Table(vars_, names, None, ng)


# ---- joining ------------------------------------------------------------------------------------------------

def _keys_of(T, keys):
    return [tuple(k for g in keys for k in _row_keys(T.vars[g], T.n)[i]) for i in range(T.n)]


def _join_keys(A, B, opts, fn):
    if 'keys' in opts:
        names = _texts(opts['keys'], fn) if type(opts['keys']) in (Char, Str, Cell) else [A.names[k] for k in A.var_index(opts['keys'])]
        lk = [A.names.index(n) for n in names]
        rk = [B.names.index(n) for n in names]
    else:
        lk = [A.names.index(n) for n in (_texts(opts['leftkeys'], fn) if 'leftkeys' in opts else [n for n in A.names if n in B.names])]
        rk = [B.names.index(n) for n in (_texts(opts['rightkeys'], fn) if 'rightkeys' in opts else [n for n in A.names if n in B.names])]
    if not lk or len(lk) != len(rk):
        raise err(f'MATLAB:{fn}:NoKeys', 'The tables have no key variables in common: give Keys.', fn)
    return lk, rk


def _name_clash(names_a, names_b, ka, kb):
    """Non-key variables with the same name get the table's name added (_left, _right)."""
    clash = {n for i, n in enumerate(names_a) if i not in ka} & {n for j, n in enumerate(names_b) if j not in kb}
    return clash


def _join(nargout, args):
    """join(A, B): A with the variables of B added, matched by the key
    variables (those of the same name, or 'Keys'); every key of A must be
    in B once."""
    data, opts, _ = _split_opts(args, ('keys', 'leftkeys', 'rightkeys', 'leftvariables', 'rightvariables', 'keepone', 'keeponeduplicate'))
    _need_args(data, 2, 'join')
    A, B = _tab(data[0], 'join'), _tab(data[1], 'join')
    lk, rk = _join_keys(A, B, opts, 'join')
    bk = _keys_of(B, rk)
    pos = {}
    for i, k in enumerate(bk):
        pos.setdefault(k, i)
    rows = []
    for k in _keys_of(A, lk):
        if k not in pos:
            raise err('MATLAB:table:join:LeftKeyValueNotFound', 'Every key of the left table must be in the right table: use outerjoin or innerjoin otherwise.', 'join')
        rows.append(pos[k])
    rvars = [j for j in range(len(B.vars)) if j not in rk]
    if 'rightvariables' in opts:
        rvars = [j for j in B.var_index(opts['rightvariables']) if j not in rk]
    clash = _name_clash(A.names, [B.names[j] if j in rvars else None for j in range(len(B.names))], lk, rk)
    names = [n + '_left' if n in clash else n for n in A.names] + [B.names[j] + '_right' if B.names[j] in clash else B.names[j] for j in rvars]
    vars_ = list(A.vars) + [_take_rows(B.vars[j], rows) for j in rvars]
    return A.copy_meta(vars_, names, A.rownames, A.n)


Table.FUNCS['join'] = _join


def _outer(A, B, opts, kind, fn, argnames=None):
    lk, rk = _join_keys(A, B, opts, fn)
    an = argnames or [None, None]
    sa, sb = '_' + (an[0] or 'left'), '_' + (an[1] or 'right')
    ak, bk = _keys_of(A, lk), _keys_of(B, rk)
    bpos = {}
    for j, k in enumerate(bk):
        bpos.setdefault(k, []).append(j)
    pairs = []
    matched_b = set()
    for i, k in enumerate(ak):
        js = bpos.get(k, [])
        if js:
            for j in js:
                pairs.append((i, j))
                matched_b.add(j)
        elif kind in ('full', 'left'):
            pairs.append((i, None))
    if kind in ('full', 'right'):
        for j in range(B.n):
            if j not in matched_b:
                pairs.append((None, j))
    # sorted by the key
    def keyof(p):
        i, j = p
        return ak[i] if i is not None else bk[j]
    pairs.sort(key=keyof)
    merge = bool(num(opts['mergekeys'])) if 'mergekeys' in opts else kind == 'inner'
    avars = list(range(len(A.vars)))
    bvars = [j for j in range(len(B.vars)) if not (merge and j in rk)]
    if 'leftvariables' in opts:
        avars = A.var_index(opts['leftvariables'])
    if 'rightvariables' in opts:
        bvars = B.var_index(opts['rightvariables'])

    def column(T, k, idxs):
        return _pick_rows(T.vars[k], idxs)
    ai = [p[0] for p in pairs]
    bi_ = [p[1] for p in pairs]
    vars_, names = [], []
    clash = {A.names[k] for k in avars} & {B.names[j] for j in bvars}
    for k in avars:
        if merge and k in lk:
            # a merged key: from A where A has the row, else from B
            j = rk[lk.index(k)]
            src = [(A, i, k) if i is not None else (B, jj, j) for i, jj in pairs]
            vars_.append(_cat_rows([_take_rows(T.vars[kk], [r]) for T, r, kk in src]) if src else _missing_like(A.vars[k], 0))
            names.append(A.names[k])
            continue
        vars_.append(column(A, k, ai))
        nm = A.names[k]
        names.append(nm + sa if nm in clash else nm)
    for j in bvars:
        vars_.append(column(B, j, bi_))
        nm = B.names[j]
        names.append(nm + sb if nm in clash else nm)
    return Table(vars_, names, None, len(pairs)), ai, bi_


@bi('innerjoin', nout=3, arr=False)
def innerjoin(nargout, *args):
    """innerjoin(A, B): the rows whose keys are in both tables, sorted by the keys."""
    data, opts, an = _split_opts(args, ('keys', 'leftkeys', 'rightkeys', 'leftvariables', 'rightvariables'))
    _need_args(data, 2, 'innerjoin')
    A, B = _tab(data[0], 'innerjoin'), _tab(data[1], 'innerjoin')
    T, ai, bi_ = _outer(A, B, opts, 'inner', 'innerjoin', an)
    if nargout > 1:
        return T, out((np.array(ai, float) + 1).reshape(-1, 1)), out((np.array(bi_, float) + 1).reshape(-1, 1))
    return T


@bi('outerjoin', nout=3, arr=False)
def outerjoin(nargout, *args):
    """outerjoin(A, B): every row of both tables, matched by the keys where
    they can be, missing values where not; 'Type' 'full', 'left' or 'right';
    'MergeKeys' true makes each key one variable."""
    data, opts, an = _split_opts(args, ('keys', 'leftkeys', 'rightkeys', 'leftvariables', 'rightvariables', 'type', 'mergekeys'))
    _need_args(data, 2, 'outerjoin')
    A, B = _tab(data[0], 'outerjoin'), _tab(data[1], 'outerjoin')
    kind = sval(opts['type'], 'Type', 'outerjoin').lower() if 'type' in opts else 'full'
    if kind not in ('full', 'left', 'right'):
        raise err('MATLAB:outerjoin:InvalidType', "Type is 'full', 'left' or 'right'.", 'outerjoin')
    T, ai, bi_ = _outer(A, B, opts, kind, 'outerjoin', an)
    if nargout > 1:
        return T, out(np.array([0 if i is None else i + 1 for i in ai], float).reshape(-1, 1)), out(np.array([0 if j is None else j + 1 for j in bi_], float).reshape(-1, 1))
    return T


# ---- timetables in time ------------------------------------------------------------------------------------

_STEPS = {'yearly': 'years', 'quarterly': 'quarters', 'monthly': 'months', 'weekly': 'weeks', 'daily': 'days',
          'hourly': 'hours', 'minutely': 'minutes', 'secondly': 'seconds'}
_FIXED = {'weeks': 7 * 86400.0, 'days': 86400.0, 'hours': 3600.0, 'minutes': 60.0, 'seconds': 1.0}
_FILLS = ('fillwithmissing', 'fillwithconstant', 'previous', 'next', 'nearest', 'linear', 'spline', 'pchip', 'makima')
_AGGS = ('mean', 'median', 'mode', 'sum', 'prod', 'min', 'max', 'count', 'firstvalue', 'lastvalue')


def _tt(v, fn):
    if not isinstance(v, TimeTable):
        raise err(f'MATLAB:{fn}:InvalidInput', 'The input must be a timetable.', fn)
    return v


def _grid(times, lo, hi, unit=None, step=None):
    """Row times from lo to hi (keys, seconds): calendar units for
    datetimes, steps of fixed length from lo (or from the unit's start);
    and the key one step after the last."""
    from .timetypes import DateTime, Duration, _start_of, _next_unit, _to_wall, _from_wall
    if type(times) is DateTime and unit is not None:
        w0, w1 = float(_to_wall(np.array([lo]), times.tz)[0]), float(_to_wall(np.array([hi]), times.tz)[0])
        g = [float(_start_of(np.array([w0]), unit)[0])]
        while True:
            nxt = float(_next_unit(np.array([g[-1]]), unit, 1)[0])
            if nxt > w1:
                break
            g.append(nxt)
        keys = _from_wall(np.array(g + [nxt]), times.tz)
        return DateTime(keys[:-1].reshape(-1, 1), times.fmt, times.tz), float(keys[-1])
    if unit is not None:
        step = _FIXED.get(unit)
        if step is None:
            raise err('MATLAB:retime:InvalidTimeStep', 'Durations step by weeks, days, hours, minutes or seconds.', 'retime')
        lo = math.floor(lo / step) * step
    if not step or step <= 0 or not math.isfinite(step):
        raise err('MATLAB:retime:InvalidTimeStep', 'The time step must be a positive duration.', 'retime')
    n = max(int(math.floor((hi - lo) / step + 1e-9)) + 1, 0)
    keys = lo + step * np.arange(n)
    new = times.mapped(lambda a: keys.reshape(-1, 1)) if type(times) is Duration else DateTime(keys.reshape(-1, 1), times.fmt, times.tz)
    return new, lo + step * n


def _step_of(v):
    from .timetypes import Duration, CalDuration
    if type(v) is Duration:
        return float(v.a.reshape(-1)[0])
    if type(v) is CalDuration:
        raise err('MATLAB:retime:InvalidTimeStep', 'Give the time step as a duration, or a name such as \'monthly\'.', 'retime')
    return float(num(v))


def _new_times(times, basis, opts, fn):
    """The new row times retime or synchronize asks for, over the span of
    times, as a value of the row times' class."""
    from .timetypes import DateTime, Duration
    key = times.key().reshape(-1)
    fin = key[np.isfinite(key)]
    lo, hi = (float(fin.min()), float(fin.max())) if fin.size else (0.0, -1.0)
    if type(basis) in (DateTime, Duration):
        return times.coerce(basis).mapped(lambda a: a.reshape(-1, 1)), None
    b = sval(basis, 'new times', fn).lower()
    if b in _STEPS:
        return _grid(times, lo, hi, unit=_STEPS[b])
    if b == 'regular':
        if 'timestep' in opts:
            return _grid(times, lo, hi, step=_step_of(opts['timestep']))
        if 'samplerate' in opts:
            return _grid(times, lo, hi, step=1.0 / float(num(opts['samplerate'])))
        raise err(f'MATLAB:{fn}:NoTimeStep', "'regular' needs 'TimeStep' or 'SampleRate'.", fn)
    raise err(f'MATLAB:{fn}:InvalidNewTimes', f"The new times are a datetime or duration vector, 'regular', or one of {', '.join(_STEPS)}.", fn)


def _is_num(v):
    return type(v) is np.ndarray and v.dtype.kind in 'fiub'


async def _fill_var(v, key, nk, method, const=None, end=None):
    """One variable at the new times nk (keys) from its values at key (sorted)."""
    from scipy import interpolate
    n, m = key.size, nk.size
    if method in ('fillwithmissing', 'fillwithconstant'):
        pos = {}
        for i, k in enumerate(key):
            pos.setdefault(k, i)
        idx = [pos.get(k, -1) for k in nk]
        r = _pick_rows(v, idx)
        if method == 'fillwithconstant' and _is_num(v):
            r = np.array(r, dtype=float if v.dtype.kind in 'fb' else v.dtype, copy=True).reshape(m, -1)
            miss = np.array([i < 0 for i in idx])
            r[miss, :] = float(num(const))
        return r
    if method == 'previous':
        idx = np.searchsorted(key, nk, side='right') - 1
        return _pick_rows(v, idx)
    if method == 'next':
        idx = np.searchsorted(key, nk, side='left')
        return _pick_rows(v, [i if i < n else -1 for i in idx])
    if method == 'nearest':
        r = np.searchsorted(key, nk)
        idx = []
        for j, k in enumerate(nk):
            cands = [i for i in (r[j] - 1, r[j]) if 0 <= i < n]
            idx.append(min(cands, key=lambda i: (abs(key[i] - k), -i)) if cands else -1)
        return _pick_rows(v, idx)
    if method in ('linear', 'spline', 'pchip', 'makima'):
        if not _is_num(v):
            raise err('MATLAB:retime:InterpolationNotNumeric', f"'{method}' fills numbers only: use 'previous', 'next' or 'nearest' for the other variables.", 'retime')
        a = np.asarray(v, float).reshape(n, -1)
        res = np.full((m, a.shape[1]), np.nan)
        for j in range(a.shape[1]):
            ok = np.isfinite(a[:, j]) & np.isfinite(key)
            x, y = key[ok], a[ok, j]
            if x.size == 0:
                continue
            if x.size == 1:
                res[:, j] = np.where(nk == x[0], y[0], np.nan)
                continue
            if method == 'linear' or x.size < 3:
                f = interpolate.interp1d(x, y, fill_value='extrapolate', assume_sorted=True)
            elif method == 'spline':
                f = interpolate.CubicSpline(x, y)
            elif method == 'pchip':
                f = interpolate.PchipInterpolator(x, y, extrapolate=True)
            else:
                f = interpolate.Akima1DInterpolator(x, y, method='makima', extrapolate=True)
            res[:, j] = f(nk)
        return res
    # aggregation over bins [t_k, t_k+1), the last up to end (as long as the one before it, or open)
    if end is None:
        end = nk[-1] + (nk[-1] - nk[-2]) if m > 1 else math.inf
    edges = np.append(nk, end) if m else nk
    which = np.searchsorted(edges, key, side='right') - 1
    members = [np.flatnonzero(which == b) for b in range(m)]
    if method in ('firstvalue', 'lastvalue'):
        return _pick_rows(v, [(ix[0] if method == 'firstvalue' else ix[-1]) if ix.size else -1 for ix in members])
    if method == 'count':
        return out(np.array([float(ix.size) for ix in members]).reshape(-1, 1))
    if isinstance(method, FH):
        rows = []
        for ix in members:
            r = await method.acall(1, _take_rows(v, ix))
            rows.append(_var_value(r[0] if isinstance(r, tuple) else r))
        return _cat_rows(rows) if rows else _missing_like(v, 0)
    if not _is_num(v):
        raise err('MATLAB:retime:AggregationNotNumeric', f"'{method}' takes numbers only: use 'firstvalue', 'lastvalue' or 'count' for the other variables.", 'retime')
    a = np.asarray(v, float).reshape(n, -1)
    fns = {'mean': np.mean, 'median': np.median, 'sum': np.sum, 'prod': np.prod, 'min': np.min, 'max': np.max,
           'mode': lambda x: _mode(x) if x.size else np.nan}
    res = np.empty((m, a.shape[1]))
    for b, ix in enumerate(members):
        for j in range(a.shape[1]):
            if ix.size:
                res[b, j] = fns[method](a[ix, j])
            else:
                res[b, j] = 0.0 if method == 'sum' else 1.0 if method == 'prod' else np.nan
    return res


async def _retime(TT, new, method, const, fn, end=None):
    order = np.argsort(TT.times.key().reshape(-1), kind='stable')
    if np.any(order != np.arange(TT.n)):
        TT = TT.sub_rows(order)
    key = TT.times.key().reshape(-1)
    nk = new.key().reshape(-1)
    vars_ = [await _fill_var(v, key, nk, method, const, end) for v in TT.vars]
    o = TimeTable(vars_, list(TT.names), new)
    o.desc, o.dims = TT.desc, list(TT.dims)
    o.units, o.vdescs = (list(TT.units) if TT.units else None), (list(TT.vdescs) if TT.vdescs else None)
    return o


def _method(v, fn):
    if isinstance(v, FH):
        return v
    m = sval(v, 'method', fn).lower()
    if m not in _FILLS + _AGGS:
        raise err(f'MATLAB:{fn}:InvalidMethod', f"'{m}' is not a method {fn} knows.", fn)
    return m


@bi('retime', aw=True, arr=False)
async def retime(nargout, *args):
    """retime(TT, newTimes, method): the timetable at new row times (a
    vector, 'regular' with 'TimeStep' or 'SampleRate', or 'yearly',
    'quarterly', 'monthly', 'weekly', 'daily', 'hourly', 'minutely',
    'secondly'); its values filled ('fillwithmissing', 'fillwithconstant'
    with 'Constant', 'previous', 'next', 'nearest', 'linear', 'spline',
    'pchip', 'makima') or put together over each new time up to the next
    ('mean', 'median', 'mode', 'sum', 'prod', 'min', 'max', 'count',
    'firstvalue', 'lastvalue', or a function)."""
    data, opts, _ = _split_opts(args, ('timestep', 'samplerate', 'constant', 'endvalues', 'includededge'))
    if len(data) < 2:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'retime')
    TT = _tt(data[0], 'retime')
    new, end = _new_times(TT.times, data[1], opts, 'retime')
    method = _method(data[2], 'retime') if len(data) > 2 else 'fillwithmissing'
    return await _retime(TT, new, method, opts.get('constant', 0.0), 'retime', end)


@bi('synchronize', aw=True, arr=False)
async def synchronize(nargout, *args):
    """synchronize(TT1, TT2, ...): the timetables side by side at the
    union of their row times (or 'intersection', 'first', 'last', 'commonrange',
    a vector or a step such as 'hourly'), each filled or put together by a
    method as retime does; names they share get the inputs' names
    after them."""
    data, opts, an = _split_opts(args, ('timestep', 'samplerate', 'constant', 'endvalues', 'includededge'))
    tts = []
    k = 0
    while k < len(data) and isinstance(data[k], TimeTable):
        tts.append(data[k])
        k += 1
    if len(tts) < 1:
        raise err('MATLAB:synchronize:InvalidInput', 'The inputs start with the timetables to synchronize.', 'synchronize')
    rest = data[k:]
    basis = rest[0] if rest else Char.of('union')
    method = _method(rest[1], 'synchronize') if len(rest) > 1 else 'fillwithmissing'
    first = tts[0]
    keysets = [t.times.key().reshape(-1) for t in tts]
    keysets = [ks[np.isfinite(ks)] for ks in keysets]
    b = opt_str(basis)
    b = b.lower() if b is not None else None
    if b in ('union', 'intersection', 'first', 'last', 'commonrange'):
        if b == 'union':
            nk = np.unique(np.concatenate(keysets))
        elif b == 'intersection':
            nk = keysets[0]
            for ks in keysets[1:]:
                nk = np.intersect1d(nk, ks)
            nk = np.unique(nk)
        elif b == 'first':
            nk = np.unique(keysets[0])
        elif b == 'last':
            nk = np.unique(keysets[-1])
        else:
            lo = max(ks.min() for ks in keysets)
            hi = min(ks.max() for ks in keysets)
            nk = np.unique(np.concatenate(keysets))
            nk = nk[(nk >= lo) & (nk <= hi)]
        new, end = first.times.mapped(lambda a: nk.reshape(-1, 1)), None
    else:
        allk = np.concatenate(keysets)
        span = first.times.mapped(lambda a: np.array([[allk.min()], [allk.max()]])) if allk.size else first.times
        new, end = _new_times(span, basis, opts, 'synchronize')
    parts = [await _retime(t, t.times.coerce(new), method, opts.get('constant', 0.0), 'synchronize', end) for t in tts]
    seen = {}
    for t in parts:
        for nm in t.names:
            seen[nm] = seen.get(nm, 0) + 1
    vars_, names = [], []
    for j, t in enumerate(parts):
        tag = an[j] if an and j < len(an) and an[j] else f'{j + 1}'
        for nm, v in zip(t.names, t.vars):
            vars_.append(v)
            names.append(f'{nm}_{tag}' if seen[nm] > 1 else nm)
    o = TimeTable(vars_, names, new)
    o.dims = list(first.dims)
    return o


@bi('isregular', nout=2, arr=False)
def isregular(nargout, *args):
    """isregular(TT): true when the row times step evenly ('time'), or by
    whole 'years', 'quarters', 'months', 'weeks', 'days', 'hours',
    'minutes' or 'seconds'; the step as a second output."""
    from .timetypes import Duration, CalDuration, DateTime, _next_unit, _UNITS
    nargchk(args, 1, 2, 'isregular')
    TT = _tt(args[0], 'isregular')
    unit = sval(args[1], 'unit', 'isregular').lower() if len(args) > 1 else 'time'
    key = TT.times.key().reshape(-1)
    if unit == 'time':
        d = np.diff(key)
        ok = bool(d.size == 0 or (np.all(np.isfinite(d)) and np.all(d > 0) and np.allclose(d, d[0], rtol=1e-12, atol=1e-9)))
        step = Duration(np.array([[float(d[0]) if ok and d.size else np.nan]]))
        return (ok, step) if nargout > 1 else ok
    u = _UNITS.get(unit)
    if u is None or type(TT.times) is not DateTime:
        raise err('MATLAB:isregular:InvalidUnit', "The unit is 'time', or for datetimes 'years', 'quarters', 'months', 'weeks', 'days', 'hours', 'minutes' or 'seconds'.", 'isregular')
    w = TT.times.wall().reshape(-1)
    ok, k = False, 0
    if w.size > 1:
        for k in range(1, 100000):
            nxt = float(_next_unit(np.array([w[0]]), u, k)[0])
            if nxt >= w[1] - 1e-6:
                break
        ok = all(abs(float(_next_unit(np.array([w[0]]), u, k * i)[0]) - w[i]) < 1e-6 for i in range(w.size))
    elif w.size == 1:
        ok, k = True, 1
    if nargout <= 1:
        return ok
    mo = {'years': 12, 'quarters': 3, 'months': 1}.get(u)
    if not ok:
        z = np.array([[np.nan]])
        return ok, CalDuration(z, z, z)
    z = np.zeros((1, 1))
    if mo:
        return ok, CalDuration(np.array([[float(k * mo)]]), z, z)
    days = {'weeks': 7, 'days': 1}.get(u)
    if days:
        return ok, CalDuration(z, np.array([[float(k * days)]]), z)
    return ok, CalDuration(z, z, np.array([[float(k * _FIXED[u])]]))


# ---- reading and writing tables -------------------------------------------------------------------------------

def _xlsx_read(path, sheet=None):
    """The cells of a sheet of an .xlsx file: rows of str, float, bool or None."""
    import zipfile
    import xml.etree.ElementTree as ET
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            root = ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in root.findall('m:si', ns):
                shared.append(''.join(t.text or '' for t in si.iter('{%s}t' % ns['m'])))
        wb = ET.fromstring(z.read('xl/workbook.xml'))
        sheets = [s.get('name') for s in wb.find('m:sheets', ns)]
        rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        targets = {r.get('Id'): r.get('Target') for r in rels}
        rid_attr = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
        sheet_elems = list(wb.find('m:sheets', ns))
        if sheet is None:
            k = 0
        elif isinstance(sheet, str):
            if sheet not in sheets:
                raise err('MATLAB:readtable:SheetNotFound', f"The file has no sheet named '{sheet}'.", 'readtable')
            k = sheets.index(sheet)
        else:
            k = int(sheet) - 1
        target = targets[sheet_elems[k].get(rid_attr)]
        target = target.lstrip('/')
        if not target.startswith('xl/'):
            target = 'xl/' + target
        root = ET.fromstring(z.read(target))
    import re
    cells = {}
    maxr = maxc = 0
    for c in root.iter('{%s}c' % ns['m']):
        ref = c.get('r')
        m = re.match(r'([A-Z]+)(\d+)', ref)
        col = 0
        for ch in m.group(1):
            col = col * 26 + ord(ch) - 64
        row = int(m.group(2))
        t = c.get('t')
        v = c.find('m:v', ns)
        if t == 's':
            val = shared[int(v.text)]
        elif t == 'inlineStr':
            val = ''.join(x.text or '' for x in c.iter('{%s}t' % ns['m']))
        elif t == 'b':
            val = v is not None and v.text == '1'
        elif t == 'str':
            val = v.text if v is not None else ''
        else:
            val = float(v.text) if v is not None and v.text is not None else None
        cells[(row, col)] = val
        maxr, maxc = max(maxr, row), max(maxc, col)
    return [[cells.get((r, c)) for c in range(1, maxc + 1)] for r in range(1, maxr + 1)]


def _col_name(k):
    s = ''
    k += 1
    while k:
        k, r = divmod(k - 1, 26)
        s = chr(65 + r) + s
    return s


def _xlsx_write(path, rows, sheet='Sheet1'):
    """rows (lists of str, float, bool or None) as an .xlsx file of one sheet."""
    import zipfile
    from xml.sax.saxutils import escape
    strings = []
    sidx = {}
    body = []
    for i, row in enumerate(rows):
        cells = []
        for j, v in enumerate(row):
            ref = f'{_col_name(j)}{i + 1}'
            if v is None:
                continue
            if isinstance(v, bool):
                cells.append(f'<c r="{ref}" t="b"><v>{int(v)}</v></c>')
            elif isinstance(v, (int, float)):
                if math.isnan(v):
                    continue
                cells.append(f'<c r="{ref}"><v>{repr(float(v)) if not float(v).is_integer() else int(v)}</v></c>')
            else:
                s = str(v)
                if s not in sidx:
                    sidx[s] = len(strings)
                    strings.append(s)
                cells.append(f'<c r="{ref}" t="s"><v>{sidx[s]}</v></c>')
        body.append(f'<row r="{i + 1}">{"".join(cells)}</row>')
    main = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    files = {
        '[Content_Types].xml': '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>',
        '_rels/.rels': f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{main}" xmlns:r="{rel}"><sheets><sheet name="{escape(sheet)}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="{rel}/sharedStrings" Target="sharedStrings.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{main}"><sheetData>{"".join(body)}</sheetData></worksheet>',
        'xl/sharedStrings.xml': f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><sst xmlns="{main}" count="{len(strings)}" uniqueCount="{len(strings)}">' + ''.join(f'<si><t xml:space="preserve">{escape(s)}</t></si>' for s in strings) + '</sst>',
    }
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, text)


def _text_rows(path, delim):
    with open(path, encoding='utf-8-sig', errors='replace', newline='') as f:
        text = f.read()
    lines = [l for l in text.splitlines() if l.strip() != '']
    if delim is None:
        sample = '\n'.join(lines[:20])
        counts = {d: sample.count(d) for d in (',', '\t', ';', '|')}
        delim = max(counts, key=counts.get) if max(counts.values()) else ' '
    if delim == ' ':
        return [l.split() for l in lines]
    return [list(r) for r in csv.reader(lines, delimiter=delim, skipinitialspace=True)]


def _column(vals, texttype):
    """A variable from one column of cells (text, numbers or empty): numbers
    when every filled cell is one, datetimes when every one reads as a date,
    else text."""
    from .timetypes import _parse_auto, DateTime, DATE
    filled = [v for v in vals if v not in (None, '')]
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in filled):
        return np.array([np.nan if v in (None, '') else float(v) for v in vals]).reshape(-1, 1)
    if filled and all(isinstance(v, bool) for v in filled):
        return np.array([bool(v) for v in vals]).reshape(-1, 1)
    nums = []
    ok = True
    for v in vals:
        if v in (None, ''):
            nums.append(np.nan)
            continue
        try:
            nums.append(float(str(v).strip()) if not isinstance(v, bool) else float(v))
        except ValueError:
            if str(v).strip().lower() in ('nan', 'na', '-nan'):
                nums.append(np.nan)
                continue
            ok = False
            break
    if ok:
        return np.array(nums).reshape(-1, 1)
    texts = ['' if v is None else str(v) for v in vals]
    if filled and all(isinstance(v, str) for v in filled):
        try:
            w, fmt = _parse_auto(texts)
            if np.sum(np.isfinite(w)) == len(filled):
                return DateTime(w.reshape(-1, 1), fmt)
        except MError:
            pass
    if texttype == 'string':
        return Str(np.array([None if t == '' else t for t in texts], object).reshape(-1, 1))
    return Cell(np.array([Char.of(t) for t in texts] + [None], object)[:-1].reshape(-1, 1))


@bi('readtable', arr=False)
def readtable(nargout, *args):
    """readtable(filename): a table from a delimited text file (.csv, .txt,
    .dat) or a spreadsheet (.xlsx), the first row its variable names; each
    column numbers, datetimes or text. Options 'Delimiter',
    'ReadVariableNames', 'ReadRowNames', 'NumHeaderLines', 'Sheet',
    'TextType' ('char' or 'string'), 'VariableNamingRule' ('modify' or
    'preserve')."""
    data, opts, _ = _split_opts(args, ('delimiter', 'readvariablenames', 'readrownames', 'numheaderlines', 'sheet', 'texttype',
                                       'variablenamingrule', 'filetype', 'headerlines', 'range'))
    from .iofun import _existing
    _need_args(data, 1, 'readtable')
    p = _existing(data[0], 'readtable')
    ext = os.path.splitext(p)[1].lower()
    ftype = sval(opts['filetype'], 'FileType', 'readtable').lower() if 'filetype' in opts else ('spreadsheet' if ext in ('.xlsx', '.xlsm') else 'text')
    if ftype == 'spreadsheet':
        sh = opts.get('sheet')
        rows = _xlsx_read(p, None if sh is None else (py_str(sh) if is_str(sh) else int(num(sh))))
    else:
        d = sval(opts['delimiter'], 'Delimiter', 'readtable') if 'delimiter' in opts else None
        d = {'comma': ',', 'tab': '\t', '\\t': '\t', 'semi': ';', 'space': ' ', 'bar': '|'}.get(d, d)
        rows = _text_rows(p, d)
    skip = int(num(opts.get('numheaderlines', opts.get('headerlines', 0.0)))) if ('numheaderlines' in opts or 'headerlines' in opts) else 0
    rows = rows[skip:]
    readnames = bool(num(opts['readvariablenames'])) if 'readvariablenames' in opts else True
    texttype = sval(opts['texttype'], 'TextType', 'readtable').lower() if 'texttype' in opts else 'char'
    rule = sval(opts['variablenamingrule'], 'VariableNamingRule', 'readtable').lower() if 'variablenamingrule' in opts else 'modify'
    if not rows:
        return Table([], [], None, 0)
    w = max(len(r) for r in rows)
    rows = [list(r) + [None] * (w - len(r)) for r in rows]
    if readnames:
        head = ['' if x is None else str(x).strip() for x in rows[0]]
        rows = rows[1:]
        names = []
        for k, h in enumerate(head):
            if not h:
                h = f'Var{k + 1}'
            if rule == 'modify' and not _valid_name(h):
                h = py_str(R.BUILTINS['matlab.lang.makeValidName'].fn(1, Char.of(h)))
            while h in names:
                h = h + '_1'
            names.append(h)
    else:
        names = [f'Var{k + 1}' for k in range(w)]
    if ftype != 'spreadsheet':
        rows = [[None if v is None else (v.strip() if isinstance(v, str) else v) for v in r] for r in rows]
    vars_ = [_column([r[k] for r in rows], texttype) for k in range(w)]
    rn = None
    if 'readrownames' in opts and bool(num(opts['readrownames'])):
        first = vars_.pop(0)
        names.pop(0)
        rn = [str(x) for x in (text_list(first) if type(first) in (Cell, Str) else [_num_text(v) for v in np.asarray(first).reshape(-1)])]
    return Table(vars_, names, rn, len(rows))


def _num_text(x):
    return str(int(x)) if np.isfinite(x) and x == int(x) else repr(float(x))


def _cell_rows(T, with_names, with_rownames):
    """The table as rows of str, float, bool or None (multi-column variables spread out as Name_1, Name_2, ...)."""
    cols, heads = [], []
    if with_rownames and T.rownames is not None:
        cols.append(list(T.rownames))
        heads.append(T.dims[0])
    if isinstance(T, TimeTable):
        cols.append([str(x) for x in np.asarray(T.times.elem_strings(), object).reshape(-1)])
        heads.append(T.dims[0])
    for nm, v in zip(T.names, T.vars):
        w = shape_of(v)[1] if len(shape_of(v)) > 1 else 1
        for j in range(w):
            heads.append(nm if w == 1 else f'{nm}_{j + 1}')
            if isinstance(v, VObj):
                s = np.asarray(v.elem_strings(), object).reshape(T.n, -1)[:, j]
                cols.append(['' if x in ('NaT', '<undefined>') else str(x) for x in s])
            elif type(v) is Cell:
                a = v.a.reshape(T.n, -1)[:, j]
                cols.append([x.str() if type(x) is Char else py_str(x) if type(x) is Str else (float(np.asarray(x).reshape(-1)[0]) if numel(x) == 1 else '') for x in a])
            elif type(v) is Str:
                cols.append(['' if s is None else s for s in v.a.reshape(T.n, -1)[:, j]])
            elif type(v) is Char:
                cols.append(v.row_strs())
            else:
                a = np.asarray(v).reshape(T.n, -1)[:, j]
                cols.append([bool(x) if a.dtype == bool else float(x) for x in a])
    rows = [heads] if with_names else []
    for i in range(T.n):
        rows.append([c[i] for c in cols])
    return rows


@bi('writetable', arr=False)
def writetable(nargout, *args):
    """writetable(T, filename): the table as a comma-separated text file (or
    .txt, .dat with 'Delimiter'), or an .xlsx spreadsheet; the variable names
    as the first row. Options 'Delimiter', 'WriteVariableNames',
    'WriteRowNames', 'QuoteStrings'."""
    data, opts, _ = _split_opts(args, ('delimiter', 'writevariablenames', 'writerownames', 'quotestrings', 'filetype', 'sheet', 'writemode'))
    _need_args(data, 1, 'writetable')
    T = _tab(data[0], 'writetable')
    name = sval(data[1], 'file name', 'writetable') if len(data) > 1 else 'table.txt'
    from .iofun import abspath, files_changed
    p = abspath(name)
    ext = os.path.splitext(p)[1].lower()
    rows = _cell_rows(T, bool(num(opts['writevariablenames'])) if 'writevariablenames' in opts else True,
                      bool(num(opts['writerownames'])) if 'writerownames' in opts else False)
    try:
        if ext in ('.xlsx', '.xlsm'):
            _xlsx_write(p, rows, py_str(opts['sheet']) if 'sheet' in opts and is_str(opts['sheet']) else 'Sheet1')
        else:
            d = sval(opts['delimiter'], 'Delimiter', 'writetable') if 'delimiter' in opts else ','
            d = {'comma': ',', 'tab': '\t', '\\t': '\t', 'semi': ';', 'space': ' ', 'bar': '|'}.get(d, d)
            quote = bool(num(opts['quotestrings'])) if 'quotestrings' in opts else False
            with open(p, 'w', encoding='utf-8', newline='') as f:
                for r in rows:
                    cells = []
                    for x in r:
                        if isinstance(x, bool):
                            cells.append('1' if x else '0')
                        elif isinstance(x, float):
                            cells.append('' if math.isnan(x) else (str(int(x)) if x.is_integer() and abs(x) < 1e15 else repr(x)))
                        else:
                            s = str(x)
                            if quote or d in s or '"' in s or '\n' in s:
                                s = '"' + s.replace('"', '""') + '"'
                            cells.append(s)
                    f.write(d.join(cells) + '\n')
    except OSError as e:
        raise err('MATLAB:writetable:CannotOpenFile', f'Unable to write {name}: {e.strerror or e}.', 'writetable')
    files_changed(os.path.dirname(p))
    return None


# ---- summary of a table -----------------------------------------------------------------------------------

def _summary_table(T):
    """summary(T): each variable's size and class, units and description,
    and its values in short (min, median, max and missing for numbers and
    times, counts for categories and logicals)."""
    from .categoricals import Categorical
    from .timetypes import DateTime, Duration
    lines = []
    if T.desc:
        lines += [f'Description:  {T.desc}', '']
    if isinstance(T, TimeTable):
        lines += ['RowTimes:', '', f'    {T.dims[0]}: {size_text(T.times)} {class_of(T.times)}', '']
    lines += ['Variables:', '']
    for k, (nm, v) in enumerate(zip(T.names, T.vars)):
        kind = class_of(v)
        if type(v) is Cell and all(type(x) is Char and x.a.shape[0] <= 1 for x in v.a.flat):
            kind = 'cell array of character vectors'
        lines += [f'    {nm}: {size_text(v)} {kind}', '']
        props = []
        if T.units and T.units[k]:
            props.append(f'            Units:  {T.units[k]}')
        if T.vdescs and T.vdescs[k]:
            props.append(f'            Description:  {T.vdescs[k]}')
        if props:
            lines += ['        Properties:'] + props
        rows = []
        if isinstance(v, Categorical):
            rows = [(c, str(int(np.sum(v.a == i + 1)))) for i, c in enumerate(v.cats)]
            und = int(np.sum(v.a == 0))
            if und:
                rows.append(('<undefined>', str(und)))
        elif type(v) in (DateTime, Duration):
            key = v.key().reshape(-1)
            fin = np.flatnonzero(np.isfinite(key))
            if fin.size:
                vals = np.asarray(v.a, float).reshape(-1, order='F')[fin]
                pick = v.mapped(lambda a: np.array([[vals.min(), np.median(vals), vals.max()]]))
                strs = np.asarray(pick.elem_strings(), object).reshape(-1)
                rows = [('Min', str(strs[0])), ('Median', str(strs[1])), ('Max', str(strs[2]))]
            miss = int(key.size - fin.size)
            if miss:
                rows.append(('NumMissing', str(miss)))
        elif type(v) is np.ndarray and v.dtype == bool:
            rows = [('True', str(int(np.sum(v)))), ('False', str(int(v.size - np.sum(v))))]
        elif type(v) is np.ndarray and v.dtype.kind in 'iuf':
            a = np.asarray(v, float).reshape(-1)
            fin = a[np.isfinite(a)]
            if fin.size:
                rows = [(lab, '%.5g' % val) for lab, val in (('Min', fin.min()), ('Median', np.median(fin)), ('Max', fin.max()))]
            miss = int(np.sum(np.isnan(a)))
            if miss:
                rows.append(('NumMissing', str(miss)))
        if rows:
            lw = max(len(r[0]) for r in rows)
            vw = max(len(r[1]) for r in rows)
            lines += ['        Values:', ''] + [f'            {lab.ljust(lw)}    {val.rjust(vw)}' for lab, val in rows]
        if props or rows:
            lines.append('')
    return lines


def size_text(v):
    from ..values import size_str
    return size_str(shape_of(v))


def _summary(nargout, args):
    T = args[0]
    if not isinstance(T, Table):
        return NotImplemented
    R.write('\n'.join(_summary_table(T)) + '\n')
    return None


Table.FUNCS['summary'] = _summary


def classes():
    return (Table, TimeTable, _VarType, _TimeRange)
