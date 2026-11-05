"""Datastores: collections of files (or an array) read a block at a time.

datastore picks the kind from the files: delimited text (TabularText), spreadsheets,
images, Parquet files, MAT-files that mapreduce wrote (KeyValue), or any file with
a function that reads it (fileDatastore). Each is a handle object with read,
readall, hasdata, reset, preview, partition, numpartitions, progress, shuffle,
subset and writeall; transform and combine make datastores of datastores;
arrayDatastore reads an array in memory. mapreduce runs a map function on each
block and a reduce function on each key's values, through key-value stores.

The files are read whole, one at a time, by the readers the engine has
(readtable, imread, parquetread), and served in blocks of ReadSize.
"""
import os
import glob
import math

import numpy as np

from . import bi as _register, REG, Info
from ._util import err, nargchk, darr, out, opt_str, is_str, sval, num
from ..values import MError, Obj, Char, Cell, Struct, FH, Str, EMPTY, numel, py_str, shape_of, class_of
from .. import runtime as R


def bi(*names, **kw):
    """Registered as builtins are, with what NumPy refuses told as the function's own error."""
    def deco(f):
        if kw.get('aw'):
            async def g(*a):
                try:
                    return await f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, KeyError, ZeroDivisionError) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        else:
            def g(*a):
                try:
                    return f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, KeyError, ZeroDivisionError) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


TEXT_EXT = ['.csv', '.txt', '.dat', '.tsv', '.tab', '.text']
SHEET_EXT = ['.xlsx', '.xlsm']
IMAGE_EXT = ['.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff', '.pgm', '.ppm', '.pbm', '.pnm', '.webp']
PARQUET_EXT = ['.parquet', '.parq']


def _texts(v, fn, what='The location'):
    """A list of texts from text, a string array or a cell of texts."""
    if type(v) is Char:
        return [v.str()]
    if type(v) is Str:
        return ['' if s is None else s for s in v.a.reshape(-1, order='F')]
    if type(v) is Cell and all(is_str(c) for c in v.a.reshape(-1)):
        return [py_str(c) for c in v.a.reshape(-1, order='F')]
    raise err(f'MATLAB:{fn}:InvalidLocation', f'{what} is text, a string array or a cell array of texts.', fn)


def _cellcol(items):
    return Cell.of_list([Char.of(s) for s in items], (len(items), 1))


def _flag(v, fn, what):
    if is_str(v):
        s = py_str(v).lower()
        if s in ('on', 'true'):
            return True
        if s in ('off', 'false'):
            return False
    a = np.asarray(darr(v)).reshape(-1)
    if a.size != 1:
        raise err(f'MATLAB:{fn}:InvalidFlag', f'{what} is true or false.', fn)
    return bool(a[0])


def find_files(location, fn, exts=None, subfolders=False):
    """The files a location names: files, folders (their files with these
    extensions, in subfolders too when asked) and wildcards; sorted by name
    within each folder, in the order the locations are given."""
    from .iofun import abspath
    files = []
    for item in _texts(location, fn):
        p = abspath(item)
        if any(c in item for c in '*?['):
            hits = sorted(glob.glob(p, recursive=True))
            if not hits:
                raise err(f'MATLAB:{fn}:FileNotFound', f"Cannot find files or folders matching '{item}'.", fn)
            for h in hits:
                if os.path.isdir(h):
                    files += _folder_files(h, exts, subfolders)
                elif os.path.isfile(h) and not os.path.basename(h).startswith('.'):
                    files.append(h)
        elif os.path.isdir(p):
            files += _folder_files(p, exts, subfolders)
        elif os.path.isfile(p):
            files.append(p)
        else:
            raise err(f'MATLAB:{fn}:FileNotFound', f"Cannot find files or folders matching '{item}'.", fn)
    if not files:
        raise err(f'MATLAB:{fn}:NoFiles', 'The location holds no files of a kind this datastore reads.', fn)
    return files


def _folder_files(folder, exts, subfolders):
    found = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        for n in sorted(names):
            if n.startswith('.'):
                continue
            if exts is None or os.path.splitext(n)[1].lower() in exts:
                found.append(os.path.join(root, n))
        if not subfolders:
            break
    return found


def _exts_opt(v, fn):
    e = [s.lower() if s.startswith('.') else '.' + s.lower() for s in _texts(v, fn, 'FileExtensions')]
    return e


def _size_of(p):
    try:
        return float(os.path.getsize(p))
    except OSError:
        return 0.0


def _split(args, names, fn):
    """Positional arguments, then Name, Value pairs among these names (any case)."""
    pos, opts = [], {}
    k = 0
    args = list(args)
    while k < len(args):
        o = opt_str(args[k])
        if o is not None and o.lower() in names and k + 1 < len(args):
            opts[o.lower()] = args[k + 1]
            k += 2
            continue
        if opts:
            raise err(f'MATLAB:{fn}:InvalidParameter', f"'{o if o is not None else class_of(args[k])}' is not an option of {fn}.", fn)
        pos.append(args[k])
        k += 1
    return pos, opts


async def _call(f, nargout, *args):
    """A function handle (or a function's name) called from a datastore."""
    if is_str(f):
        return await R.call(None, py_str(f), nargout, args)
    if not isinstance(f, FH):
        raise err('MATLAB:datastore:InvalidFunction', 'The function is a function handle.', 'datastore')
    return await f.acall(nargout, *args)


# ---- joining what reads give ------------------------------------------------------------------------------------------------

def vjoin(parts):
    """The blocks a datastore read, one under another (tables, arrays and cells)."""
    from .tables import Table
    parts = [p for p in parts if p is not None]
    if not parts:
        return EMPTY()
    if len(parts) == 1:
        return parts[0]
    if isinstance(parts[0], Table):
        return type(parts[0]).concat(0, parts)
    from .. import ops
    return ops.vcat(parts)


def hjoin(parts):
    """What the datastores of a combined datastore read, side by side:
    tables as one table, cells joined, anything else each in a cell."""
    from .tables import Table
    if all(isinstance(p, Table) for p in parts):
        return Table.concat(1, parts)
    cells = [p if type(p) is Cell else Cell.of_list([p], (1, 1)) for p in parts]
    rows = max(c.a.shape[0] for c in cells)
    cells = [c if c.a.shape[0] == rows else Cell(np.tile(c.a, (rows, 1))) for c in cells]
    return Cell(np.hstack([c.a for c in cells]))


# ---- the datastores ------------------------------------------------------------------------------------------------------

METHODS = ('read', 'readall', 'hasdata', 'reset', 'preview', 'partition', 'numpartitions', 'progress', 'shuffle', 'subset',
           'transform', 'combine', 'writeall', 'isPartitionable', 'isShuffleable', 'countEachLabel', 'splitEachLabel', 'readimage', 'copy')


class Datastore(Obj):
    """What every datastore has: files read in order, a place in them, and the methods."""
    is_handle = True
    name = 'Datastore'
    PROPS = ()                 # the properties, in the order the display shows them
    SETTABLE = ()
    file_based = True

    def __init__(self):
        self.files = []
        self.fi = 0             # the file being read
        self.labels = None

    @property
    def cls(self):
        return 'matlab.io.datastore.' + self.name

    def value_copy(self):
        return self

    def copy(self):
        import copy
        o = copy.copy(self)
        o.files = list(self.files)
        return o

    # properties
    def getprop(self, name):
        for p in self.PROPS:
            if p.lower() == name.lower():
                return self.get(p)
        for m in METHODS:
            if m.lower() == name.lower():
                from ..classdef import BoundBuiltin
                return BoundBuiltin(self, m)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{self.cls}'.")

    def setprop(self, name, value):
        for p in self.SETTABLE:
            if p.lower() == name.lower():
                self.set(p, value)
                return
        for p in self.PROPS:
            if p.lower() == name.lower():
                raise MError('MATLAB:class:SetProhibited', f"You cannot set the '{p}' property of {self.name}.")
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class '{self.cls}'.")

    def propnames(self):
        return list(self.PROPS)

    def get(self, p):
        if p == 'Files':
            return _cellcol(self.files)
        if p == 'Folders':
            return _cellcol(_folders(self.files))
        if p == 'Labels':
            return self.labels if self.labels is not None else Cell(np.empty((0, 1), object))
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{p}' for class '{self.cls}'.")

    def set(self, p, value):
        if p == 'Files':
            self.files = find_files(value, 'datastore')
            self.reset()
            return
        if p == 'Labels':
            self.labels = _labels_value(value, len(self.files))
            return
        raise MError('MATLAB:class:SetProhibited', f"You cannot set the '{p}' property of {self.name}.")

    def display_lines(self):
        lines = [f'  {self.name} with properties:', '']
        w = max(len(p) for p in self.PROPS) if self.PROPS else 0
        for p in self.PROPS:
            lines += _prop_lines(p, self.get(p), w)
        return lines

    # reading
    def hasdata(self):
        return self.fi < len(self.files)

    def reset(self):
        self.fi = 0

    async def read(self):
        raise NotImplementedError

    async def readall(self):
        c = self.copy()
        c.reset()
        parts = []
        while c.hasdata():
            parts.append((await c.read())[0])
        return vjoin(parts)

    async def preview(self):
        c = self.copy()
        c.reset()
        if not c.hasdata():
            return EMPTY()
        return (await c.read())[0]

    def progress(self):
        return float(self.fi / len(self.files)) if self.files else 1.0

    def numpartitions(self):
        return float(len(self.files))

    def part_of(self, n, i):
        """The datastore of the i-th of n parts (0-based), by files."""
        k = len(self.files)
        lo, hi = (i * k) // n, ((i + 1) * k) // n
        return self.with_files(list(range(lo, hi)))

    def with_files(self, idx):
        o = self.copy()
        o.files = [self.files[i] for i in idx]
        if self.labels is not None:
            from ..index import idx as take
            o.labels = take(self.labels, (out(np.asarray(idx, float).reshape(-1, 1) + 1),))
        o.reset()
        return o

    def info(self, p, **more):
        d = {'Filename': Char.of(p), 'FileSize': _size_of(p)}
        d.update(more)
        return Struct.scalar(d)


def _folders(files):
    seen = []
    for f in files:
        d = os.path.dirname(f)
        if d not in seen:
            seen.append(d)
    return seen


def _labels_value(v, n):
    if numel(v) != n:
        raise err('MATLAB:datastore:LabelsSize', f'There are {n} files: give one label each.', 'datastore')
    from ..index import idx as take
    return take(v, (out(np.arange(1, n + 1, dtype=float).reshape(-1, 1)),)) if shape_of(v)[0] != n else v


def _prop_lines(p, v, w):
    """One property as the datastore's display shows it."""
    lab = ' ' * (w - len(p) + 4) + p + ': '
    pad = ' ' * len(lab)
    if type(v) is Cell and v.a.shape[1] <= 1 and all(type(x) is Char for x in v.a.reshape(-1)):
        items = [x.str() for x in v.a.reshape(-1)]
        if not items:
            return [lab + '{}']
        shown = items[:3]
        rows = [lab + '{']
        for k, s in enumerate(shown):
            rows.append(pad + "'" + s + "'" + (';' if k < len(shown) - 1 or len(items) > 3 else ''))
        if len(items) > 3:
            rows.append(pad + f' ... and {len(items) - 3} more')
        rows.append(pad + '}')
        return rows
    if type(v) is Cell:
        items = [x.str() if type(x) is Char else class_of(x) for x in v.a.reshape(-1, order='F')]
        return [lab + '{' + ', '.join("'" + s + "'" for s in items) + '}']
    if type(v) is Char:
        return [lab + "'" + v.str().replace('\t', '\\t').replace('\r', '\\r').replace('\n', '\\n') + "'"]
    if type(v) is bool or (type(v) is np.ndarray and v.dtype == bool and v.size == 1):
        return [lab + ('true' if bool(np.asarray(v).reshape(-1)[0]) else 'false')]
    if type(v) is float:
        return [lab + (f'{v:g}' if math.isfinite(v) else ('Inf' if v > 0 else 'NaN'))]
    if isinstance(v, FH):
        return [lab + '@' + v.name() if not v.text().startswith('@') else lab + v.text()]
    if isinstance(v, Obj):
        return [lab + f'[{"×".join(str(d) for d in shape_of(v))} {class_of(v)}]']
    if type(v) is np.ndarray:
        if v.size <= 6 and v.ndim == 2:
            return [lab + '[' + ' '.join(f'{x:g}' for x in v.reshape(-1)) + ']']
        return [lab + f'[{"×".join(str(d) for d in v.shape)} {class_of(v)}]']
    return [lab + f'[{"×".join(str(d) for d in shape_of(v))} {class_of(v)}]']


# ---- tables from text and spreadsheets -------------------------------------------------------------------------------------

class _TableStore(Datastore):
    """A datastore whose files read as tables, served ReadSize rows at a time."""

    def __init__(self):
        super().__init__()
        self.readsize = 20000.0       # rows, or 'file'
        self.names = []               # the variable names (from the first file unless set)
        self.selected = None          # the names read, all unless set
        self.texttype = 'char'
        self.readnames = True
        self.headers = 0.0
        self.outtype = 'table'
        self.cur = None               # the file being read, as a table
        self.row = 0
        self.offsets = None

    def reset(self):
        self.fi = 0
        self.cur = None
        self.row = 0

    def hasdata(self):
        if self.cur is not None and self.row < self.cur.n:
            return True
        return self.fi < len(self.files) - (1 if self.cur is not None else 0)

    def copy(self):
        o = super().copy()
        o.names = list(self.names)
        o.selected = list(self.selected) if self.selected is not None else None
        return o

    def _table(self, p):
        """One file as a table with the store's names and selection."""
        T = self.read_file(p)
        if len(T.names) != len(self.names):
            raise err('MATLAB:datastore:VariableCount', f"{os.path.basename(p)} has {len(T.names)} variables, the datastore {len(self.names)}.", 'read')
        T.names = list(self.names)
        if self.selected is not None:
            T = T.sub_vars([self.names.index(s) for s in self.selected])
        return T

    async def read(self):
        if not self.hasdata():
            raise err('MATLAB:datastoreio:splittabledatastore:noMoreData', 'No more data to read. Use reset to read from the start, or hasdata to check first.', 'read')
        if self.cur is None or self.row >= self.cur.n:
            if self.cur is not None:
                self.fi += 1
            self.cur = self._table(self.files[self.fi])
            self.row = 0
        p = self.files[self.fi]
        n = self.cur.n if self.readsize == 'file' else int(self.readsize)
        lo, hi = self.row, min(self.row + n, self.cur.n)
        T = self.cur.sub_rows(np.arange(lo, hi))
        self.row = hi
        info = self.info(p, **self.where(lo))
        if self.row >= self.cur.n and self.fi == len(self.files) - 1:
            self.fi = len(self.files)
            self.cur = None
        return self.output(T), info

    def where(self, row):
        return {}

    def output(self, T):
        if self.outtype == 'timetable':
            return R.BUILTINS['table2timetable'].fn(1, T)
        return T

    async def readall(self):
        parts = [self.output(self._table(p)) for p in self.files]
        return vjoin(parts)

    async def preview(self):
        T = self._table(self.files[0])
        return self.output(T.sub_rows(np.arange(min(8, T.n))))

    def progress(self):
        if not self.files:
            return 1.0
        done = self.fi + (self.row / self.cur.n if self.cur is not None and self.cur.n else 0.0)
        return float(min(1.0, done / len(self.files)))

    def get(self, p):
        if p == 'VariableNames':
            return Cell.of_list([Char.of(s) for s in self.names], (1, len(self.names)))
        if p == 'SelectedVariableNames':
            s = self.selected if self.selected is not None else self.names
            return Cell.of_list([Char.of(x) for x in s], (1, len(s)))
        if p == 'ReadSize':
            return Char.of(self.readsize) if isinstance(self.readsize, str) else self.readsize
        if p == 'TextType':
            return Char.of(self.texttype)
        if p == 'ReadVariableNames':
            return self.readnames
        if p == 'NumHeaderLines':
            return self.headers
        if p == 'OutputType':
            return Char.of(self.outtype)
        return super().get(p)

    def set(self, p, value):
        if p == 'VariableNames':
            names = _texts(value, 'datastore', 'VariableNames')
            if len(names) != len(self.names):
                raise err('MATLAB:datastore:VariableCount', f'Give {len(self.names)} variable names.', 'datastore')
            if len(set(names)) != len(names):
                raise err('MATLAB:table:DuplicateVarNames', 'The variable names differ from one another.', 'datastore')
            if self.selected is not None:
                self.selected = [names[self.names.index(s)] for s in self.selected]
            self.names = names
            self.reset()
            return
        if p == 'SelectedVariableNames':
            sel = _texts(value, 'datastore', 'SelectedVariableNames')
            bad = [s for s in sel if s not in self.names]
            if bad:
                raise err('MATLAB:datastore:UnknownVariable', f"'{bad[0]}' is not one of the variable names.", 'datastore')
            self.selected = sel
            self.reset()
            return
        if p == 'ReadSize':
            if is_str(value):
                s = py_str(value).lower()
                if s not in ('file',) + (('sheet',) if self.name == 'SpreadsheetDatastore' else ()):
                    raise err('MATLAB:datastore:InvalidReadSize', "ReadSize is a number of rows or 'file'.", 'datastore')
                self.readsize = s
            else:
                n = float(num(value))
                if not (n >= 1 and n == int(n)):
                    raise err('MATLAB:datastore:InvalidReadSize', 'ReadSize is a whole number of rows from 1.', 'datastore')
                self.readsize = n
            return
        if p == 'OutputType':
            s = (opt_str(value) or '').lower()
            if s not in ('table', 'timetable'):
                raise err('MATLAB:datastore:InvalidOutputType', "OutputType is 'table' or 'timetable'.", 'datastore')
            self.outtype = s
            return
        super().set(p, value)


class TabularText(_TableStore):
    name = 'TabularTextDatastore'
    PROPS = ('Files', 'Folders', 'FileEncoding', 'ReadVariableNames', 'VariableNames', 'NumHeaderLines', 'Delimiter',
             'TextType', 'SelectedVariableNames', 'ReadSize', 'OutputType')
    SETTABLE = ('Files', 'VariableNames', 'SelectedVariableNames', 'ReadSize', 'OutputType')

    def __init__(self, files, delim=None, headers=0.0, readnames=True, texttype='char', rule='modify'):
        super().__init__()
        self.files = files
        self.headers, self.readnames, self.texttype, self.rule = float(headers), readnames, texttype, rule
        self.delim = delim if delim is not None else _sniff(files[0])
        self.names = list(self.read_file(files[0]).names)

    def read_file(self, p):
        from .tables import readtable
        args = [Char.of(p), Char.of('Delimiter'), Char.of(self.delim), Char.of('NumHeaderLines'), self.headers,
                Char.of('ReadVariableNames'), self.readnames, Char.of('TextType'), Char.of(self.texttype),
                Char.of('VariableNamingRule'), Char.of(self.rule)]
        T = readtable(1, *args)
        self.offsets = (p, _line_offsets(p))
        return T

    def where(self, row):
        p, offs = self.offsets if self.offsets is not None else (None, [])
        k = int(self.headers) + (1 if self.readnames else 0) + row
        return {'Offset': float(offs[k]) if p == self.files[self.fi] and k < len(offs) else 0.0}

    def get(self, p):
        if p == 'Delimiter':
            return Char.of(self.delim)
        if p == 'FileEncoding':
            return Char.of('UTF-8')
        return super().get(p)


def _sniff(p):
    """The delimiter a text file uses (as readtable chooses it)."""
    try:
        with open(p, encoding='utf-8-sig', errors='replace', newline='') as f:
            lines = [l for l in f.read(65536).splitlines() if l.strip()][:20]
    except OSError:
        return ','
    sample = '\n'.join(lines)
    counts = {d: sample.count(d) for d in (',', '\t', ';', '|')}
    return max(counts, key=counts.get) if max(counts.values()) else ' '


def _line_offsets(p):
    """Where each line that is not blank starts, in bytes."""
    offs = []
    pos = 0
    try:
        with open(p, 'rb') as f:
            data = f.read()
    except OSError:
        return offs
    if data.startswith(b'\xef\xbb\xbf'):
        pos = 3
        data = data[3:]
    for line in data.splitlines(keepends=True):
        if line.strip():
            offs.append(pos)
        pos += len(line)
    return offs


class Spreadsheet(_TableStore):
    name = 'SpreadsheetDatastore'
    PROPS = ('Files', 'Folders', 'Sheets', 'Range', 'NumHeaderLines', 'ReadVariableNames', 'VariableNames', 'TextType',
             'SelectedVariableNames', 'ReadSize', 'OutputType')
    SETTABLE = ('Files', 'Sheets', 'VariableNames', 'SelectedVariableNames', 'ReadSize', 'OutputType')

    def __init__(self, files, sheets=None, headers=0.0, readnames=True, texttype='char'):
        super().__init__()
        self.files = files
        self.sheets = sheets            # names or 1-based numbers; None: the first sheet
        self.headers, self.readnames, self.texttype = float(headers), readnames, texttype
        self.readsize = 'file'
        self.names = list(self.read_file(files[0]).names)

    def _sheet_list(self):
        return self.sheets if self.sheets else [1.0]

    def read_sheet(self, p, sh):
        from .tables import readtable
        return readtable(1, Char.of(p), Char.of('FileType'), Char.of('spreadsheet'), Char.of('Sheet'), Char.of(sh) if isinstance(sh, str) else sh,
                         Char.of('NumHeaderLines'), self.headers, Char.of('ReadVariableNames'), self.readnames, Char.of('TextType'), Char.of(self.texttype))

    def read_file(self, p):
        return vjoin([self.read_sheet(p, sh) for sh in self._sheet_list()])

    async def read(self):
        if self.readsize != 'sheet':
            return await super().read()
        # one sheet at a time: the place is (file, sheet)
        if not self.hasdata():
            raise err('MATLAB:datastoreio:splittabledatastore:noMoreData', 'No more data to read. Use reset to read from the start, or hasdata to check first.', 'read')
        sheets = self._sheet_list()
        k = self.row
        p = self.files[self.fi]
        T = self.read_sheet(p, sheets[k])
        T.names = list(self.names)
        if self.selected is not None:
            T = T.sub_vars([self.names.index(s) for s in self.selected])
        self.row += 1
        if self.row >= len(sheets):
            self.fi += 1
            self.row = 0
        return self.output(T), self.info(p, SheetNames=Char.of(sheets[k]) if isinstance(sheets[k], str) else sheets[k])

    def hasdata(self):
        if self.readsize == 'sheet':
            return self.fi < len(self.files)
        return super().hasdata()

    def get(self, p):
        if p == 'Sheets':
            if not self.sheets:
                return Char.of('')
            if all(isinstance(s, str) for s in self.sheets):
                return Cell.of_list([Char.of(s) for s in self.sheets], (1, len(self.sheets)))
            return out(np.array([self.sheets], float))
        if p == 'Range':
            return Char.of('')
        return super().get(p)

    def set(self, p, value):
        if p == 'Sheets':
            self.sheets = _sheets_value(value)
            self.reset()
            return
        super().set(p, value)


def _sheets_value(v):
    if is_str(v):
        s = py_str(v)
        return [s] if s else None
    if type(v) in (Cell, Str):
        return _texts(v, 'spreadsheetDatastore', 'Sheets')
    a = np.asarray(darr(v), float).reshape(-1)
    if np.any(a < 1) or np.any(a != np.round(a)):
        raise err('MATLAB:spreadsheetDatastore:InvalidSheets', 'Sheets are names or numbers from 1.', 'spreadsheetDatastore')
    return [float(x) for x in a]


# ---- images -----------------------------------------------------------------------------------------------------------

class ImageStore(Datastore):
    name = 'ImageDatastore'
    PROPS = ('Files', 'Folders', 'Labels', 'ReadSize', 'ReadFcn', 'SupportedOutputFormats', 'DefaultOutputFormat')
    SETTABLE = ('Files', 'Labels', 'ReadSize', 'ReadFcn')

    def __init__(self, files, labels=None, readfcn=None):
        super().__init__()
        self.files = files
        self.labels = labels
        self.readfcn = readfcn
        self.readsize = 1.0

    async def read_file(self, p):
        if self.readfcn is not None:
            return await _call(self.readfcn, 1, Char.of(p))
        return await REG['imread'].fn(1, Char.of(p))

    async def read(self):
        if not self.hasdata():
            raise err('MATLAB:datastoreio:splittabledatastore:noMoreData', 'No more data to read. Use reset to read from the start, or hasdata to check first.', 'read')
        k = int(self.readsize)
        idx = list(range(self.fi, min(self.fi + k, len(self.files))))
        imgs = [await self.read_file(self.files[i]) for i in idx]
        self.fi = idx[-1] + 1
        lab = self._labels_at(idx)
        if k == 1:
            d = {'Filename': Char.of(self.files[idx[0]]), 'FileSize': _size_of(self.files[idx[0]])}
            if lab is not None:
                d['Label'] = lab
            return imgs[0], Struct.scalar(d)
        d = {'Filename': _cellcol([self.files[i] for i in idx]), 'FileSize': out(np.array([[_size_of(self.files[i])] for i in idx]))}
        if lab is not None:
            d['Label'] = lab
        return Cell.of_list(imgs, (len(imgs), 1)), Struct.scalar(d)

    def _labels_at(self, idx):
        if self.labels is None:
            return None
        from ..index import idx as take
        return take(self.labels, (out(np.asarray(idx, float).reshape(-1, 1) + 1),))

    async def readall(self):
        imgs = [await self.read_file(p) for p in self.files]
        return Cell.of_list(imgs, (len(imgs), 1))

    def get(self, p):
        if p == 'ReadSize':
            return self.readsize
        if p == 'ReadFcn':
            return self.readfcn if self.readfcn is not None else R.NamedFH('imread')
        if p == 'SupportedOutputFormats':
            fm = ['png', 'jpg', 'jpeg', 'tif', 'tiff', 'bmp', 'gif']
            return Str(np.array([fm], object))
        if p == 'DefaultOutputFormat':
            return Char.of('png')
        return super().get(p)

    def set(self, p, value):
        if p == 'ReadSize':
            n = float(num(value))
            if not (n >= 1 and n == int(n)):
                raise err('MATLAB:imageDatastore:InvalidReadSize', 'ReadSize is a whole number of images from 1.', 'imageDatastore')
            self.readsize = n
            return
        if p == 'ReadFcn':
            if not isinstance(value, FH):
                raise err('MATLAB:imageDatastore:InvalidReadFcn', 'ReadFcn is a function handle.', 'imageDatastore')
            self.readfcn = value
            return
        super().set(p, value)


def _folder_labels(files):
    from .categoricals import Categorical
    names = [os.path.basename(os.path.dirname(f)) for f in files]
    cats = sorted(set(names))
    return Categorical(np.array([[cats.index(n) + 1.0] for n in names]).reshape(-1, 1), cats)


# ---- any file, with the function that reads it ------------------------------------------------------------------------------

class FileStore(Datastore):
    name = 'FileDatastore'
    PROPS = ('Files', 'Folders', 'UniformRead', 'ReadMode', 'BlockSize', 'PreviewFcn', 'SupportedOutputFormats', 'ReadFcn')
    SETTABLE = ('Files', 'ReadFcn', 'PreviewFcn')

    def __init__(self, files, readfcn, uniform=False, mode='file', block=float('inf'), previewfcn=None):
        super().__init__()
        self.files = files
        self.readfcn = readfcn
        self.uniform = uniform
        self.mode = mode
        self.block = block
        self.previewfcn = previewfcn
        self.pos = 0.0                  # bytes or the partial-file place
        self.state = None               # what a partialfile ReadFcn hands back

    def reset(self):
        self.fi = 0
        self.pos = 0.0
        self.state = None

    async def read(self):
        if not self.hasdata():
            raise err('MATLAB:datastoreio:splittabledatastore:noMoreData', 'No more data to read. Use reset to read from the start, or hasdata to check first.', 'read')
        p = self.files[self.fi]
        if self.mode == 'bytes':
            size = _size_of(p)
            n = int(min(self.block, size - self.pos)) if math.isfinite(self.block) else int(size - self.pos)
            with open(p, 'rb') as f:
                f.seek(int(self.pos))
                data = np.frombuffer(f.read(n), np.uint8).reshape(-1, 1).copy()
            info = self.info(p, Offset=self.pos)
            self.pos += n
            if self.pos >= size:
                self.fi += 1
                self.pos = 0.0
            return data, info
        if self.mode == 'partialfile':
            r = await _call(self.readfcn, 3, Char.of(p), Char.of('') if self.state is None else self.state)
            data, state, done = r
            done = bool(np.asarray(darr(done)).reshape(-1)[0])
            info = self.info(p)
            if done:
                self.fi += 1
                self.state = None
            else:
                self.state = state
            return data, info
        data = await _call(self.readfcn, 1, Char.of(p))
        self.fi += 1
        return data, self.info(p)

    async def readall(self):
        c = self.copy()
        c.reset()
        parts = []
        while c.hasdata():
            parts.append((await c.read())[0])
        if self.uniform:
            return vjoin(parts)
        return Cell.of_list(parts, (len(parts), 1))

    async def preview(self):
        if self.previewfcn is not None and self.files:
            return await _call(self.previewfcn, 1, Char.of(self.files[0]))
        return await super().preview()

    def get(self, p):
        if p == 'UniformRead':
            return self.uniform
        if p == 'ReadMode':
            return Char.of(self.mode)
        if p == 'BlockSize':
            return self.block
        if p == 'ReadFcn':
            return self.readfcn
        if p == 'PreviewFcn':
            return self.previewfcn if self.previewfcn is not None else self.readfcn
        if p == 'SupportedOutputFormats':
            return Str(np.array([['txt', 'csv', 'xlsx', 'xls', 'parquet', 'parq', 'png', 'jpg', 'jpeg', 'tif', 'tiff', 'wav', 'flac', 'ogg', 'mp4', 'm4a']], object))
        return super().get(p)

    def set(self, p, value):
        if p in ('ReadFcn', 'PreviewFcn'):
            if not isinstance(value, FH):
                raise err('MATLAB:fileDatastore:InvalidReadFcn', f'{p} is a function handle.', 'fileDatastore')
            if p == 'ReadFcn':
                self.readfcn = value
            else:
                self.previewfcn = value
            return
        super().set(p, value)


# ---- Parquet files ------------------------------------------------------------------------------------------------------

class ParquetStore(_TableStore):
    name = 'ParquetDatastore'
    PROPS = ('Files', 'Folders', 'VariableNames', 'SelectedVariableNames', 'ReadSize', 'OutputType')
    SETTABLE = ('Files', 'SelectedVariableNames', 'ReadSize', 'OutputType')

    def __init__(self, files, names):
        super().__init__()
        self.files = files
        self.readsize = 'file'
        self.names = names

    def read_file(self, p):
        from .fileformats import read_parquet
        return read_parquet(p, None)


# ---- an array in memory -------------------------------------------------------------------------------------------------

class ArrayStore(Datastore):
    name = 'ArrayDatastore'
    PROPS = ('ReadSize', 'IterationDimension', 'OutputType')
    SETTABLE = ('ReadSize', 'OutputType')
    file_based = False

    def __init__(self, data, readsize=1.0, dim=1, outtype='cell'):
        super().__init__()
        self.data = data
        self.readsize = float(readsize)
        self.dim = int(dim)
        self.outtype = outtype
        self.k = 0

    def count(self):
        sh = shape_of(self.data)
        return sh[self.dim - 1] if self.dim <= len(sh) else 1

    def hasdata(self):
        return self.k < self.count()

    def reset(self):
        self.k = 0

    def _slice(self, lo, hi):
        from ..index import idx as take
        sh = shape_of(self.data)
        nd = max(len(sh), self.dim)
        args = [Char.of(':')] * nd
        args[self.dim - 1] = out(np.arange(lo + 1, hi + 1, dtype=float).reshape(1, -1))
        return take(self.data, tuple(args))

    async def read(self):
        if not self.hasdata():
            raise err('MATLAB:datastoreio:splittabledatastore:noMoreData', 'No more data to read. Use reset to read from the start, or hasdata to check first.', 'read')
        lo = self.k
        hi = min(self.count(), lo + int(self.readsize))
        self.k = hi
        info = Struct.scalar({'IterationDimension': float(self.dim), 'Index': out(np.arange(lo + 1, hi + 1, dtype=float).reshape(-1, 1))})
        if self.outtype == 'same':
            return self._slice(lo, hi), info
        return Cell.of_list([self._slice(i, i + 1) for i in range(lo, hi)], (hi - lo, 1)), info

    async def readall(self):
        if self.outtype == 'same':
            return self.data
        n = self.count()
        return Cell.of_list([self._slice(i, i + 1) for i in range(n)], (n, 1))

    def progress(self):
        n = self.count()
        return float(self.k / n) if n else 1.0

    def numpartitions(self):
        return float(self.count())

    def part_of(self, n, i):
        k = self.count()
        lo, hi = (i * k) // n, ((i + 1) * k) // n
        return self.with_rows(list(range(lo, hi)))

    def with_rows(self, rows):
        o = self.copy()
        from ..index import idx as take
        sh = shape_of(self.data)
        nd = max(len(sh), self.dim)
        args = [Char.of(':')] * nd
        args[self.dim - 1] = out(np.asarray(rows, float).reshape(1, -1) + 1)
        o.data = take(self.data, tuple(args))
        o.k = 0
        return o

    def get(self, p):
        if p == 'ReadSize':
            return self.readsize
        if p == 'IterationDimension':
            return float(self.dim)
        if p == 'OutputType':
            return Char.of(self.outtype)
        return super().get(p)

    def set(self, p, value):
        if p == 'ReadSize':
            n = float(num(value))
            if not (n >= 1 and n == int(n)):
                raise err('MATLAB:arrayDatastore:InvalidReadSize', 'ReadSize is a whole number from 1.', 'arrayDatastore')
            self.readsize = n
            return
        if p == 'OutputType':
            s = (opt_str(value) or '').lower()
            if s not in ('cell', 'same'):
                raise err('MATLAB:arrayDatastore:InvalidOutputType', "OutputType is 'cell' or 'same'.", 'arrayDatastore')
            self.outtype = s
            return
        super().set(p, value)


# ---- keys and values (what mapreduce writes) -----------------------------------------------------------------------------------

class KeyValueStore(Datastore):
    name = 'KeyValueDatastore'
    PROPS = ('Files', 'ReadSize', 'FileType')
    SETTABLE = ('ReadSize',)

    def __init__(self, keys, values, files=None):
        super().__init__()
        self.keys, self.values = keys, values
        self.files = files or []
        self.readsize = 1.0
        self.k = 0

    def hasdata(self):
        return self.k < len(self.keys)

    def reset(self):
        self.k = 0

    def _table(self, lo, hi):
        from .tables import Table
        ks = self.keys[lo:hi]
        if all(isinstance(k, str) for k in ks):
            key = Cell.of_list([Char.of(k) for k in ks], (len(ks), 1))
        else:
            key = np.array([[float(k)] for k in ks]).reshape(-1, 1)
        val = Cell.of_list(self.values[lo:hi], (hi - lo, 1))
        return Table([key, val], ['Key', 'Value'])

    async def read(self):
        if not self.hasdata():
            raise err('MATLAB:datastoreio:splittabledatastore:noMoreData', 'No more data to read. Use reset to read from the start, or hasdata to check first.', 'read')
        lo = self.k
        hi = min(len(self.keys), lo + int(self.readsize))
        self.k = hi
        return self._table(lo, hi), Struct.scalar({'Filename': Char.of(self.files[0] if self.files else ''), 'Index': out(np.arange(lo + 1, hi + 1, dtype=float).reshape(-1, 1))})

    async def readall(self):
        return self._table(0, len(self.keys))

    def progress(self):
        return float(self.k / len(self.keys)) if self.keys else 1.0

    def numpartitions(self):
        return float(max(1, len(self.files)))

    def part_of(self, n, i):
        k = len(self.keys)
        lo, hi = (i * k) // n, ((i + 1) * k) // n
        o = self.copy()
        o.keys, o.values, o.k = self.keys[lo:hi], self.values[lo:hi], 0
        return o

    def get(self, p):
        if p == 'ReadSize':
            return self.readsize
        if p == 'FileType':
            return Char.of('mat')
        return super().get(p)

    def set(self, p, value):
        if p == 'ReadSize':
            n = float(num(value))
            if not (n >= 1 and n == int(n)):
                raise err('MATLAB:datastore:InvalidReadSize', 'ReadSize is a whole number from 1.', 'datastore')
            self.readsize = n
            return
        super().set(p, value)


async def _save_vars(target, d):
    """The variables written to a MAT-file, as save writes them."""
    await REG['save'].fn(dict(d), 0, Char.of(target), *[Char.of(k) for k in d])


# ---- datastores of datastores --------------------------------------------------------------------------------------------

class Transformed(Datastore):
    name = 'TransformedDatastore'
    PROPS = ('UnderlyingDatastores', 'SupportedOutputFormats', 'Transforms', 'IncludeInfo')
    file_based = False

    def __init__(self, stores, fns, include_info=False):
        super().__init__()
        self.stores = stores
        self.fns = fns                  # applied in turn
        self.include = include_info

    def copy(self):
        o = super().copy()
        o.stores = [s.copy() for s in self.stores]
        return o

    def hasdata(self):
        return all(s.hasdata() for s in self.stores)

    def reset(self):
        for s in self.stores:
            s.reset()

    async def read(self):
        reads = [await s.read() for s in self.stores]
        data = [r[0] for r in reads]
        info = reads[0][1] if len(reads) == 1 else Cell.of_list([r[1] for r in reads], (1, len(reads)))
        for k, f in enumerate(self.fns):
            if self.include[k] if isinstance(self.include, list) else self.include:
                r = await _call(f, 2, *data, info)
                data, info = [r[0]], r[1]
            else:
                data = [await _call(f, 1, *data)]
        return data[0], info

    def progress(self):
        return float(min(s.progress() for s in self.stores))

    def numpartitions(self):
        return self.stores[0].numpartitions()

    def part_of(self, n, i):
        o = self.copy()
        o.stores = [s.part_of(n, i) for s in self.stores]
        return o

    def get(self, p):
        if p == 'UnderlyingDatastores':
            return Cell.of_list(list(self.stores), (1, len(self.stores)))
        if p == 'Transforms':
            return Cell.of_list(list(self.fns), (1, len(self.fns)))
        if p == 'IncludeInfo':
            inc = self.include if isinstance(self.include, list) else [self.include]
            return inc[0] if len(inc) == 1 else out(np.array([inc], bool))
        if p == 'SupportedOutputFormats':
            return Str(np.array([['txt', 'csv', 'xlsx', 'png', 'jpg', 'tif', 'mat']], object))
        return super().get(p)


class Combined(Datastore):
    name = 'CombinedDatastore'
    PROPS = ('UnderlyingDatastores', 'SupportedOutputFormats')
    file_based = False

    def __init__(self, stores, order='associated'):
        super().__init__()
        self.stores = stores
        self.order = order
        self.si = 0

    def copy(self):
        o = super().copy()
        o.stores = [s.copy() for s in self.stores]
        return o

    def hasdata(self):
        if self.order == 'sequential':
            return any(s.hasdata() for s in self.stores[self.si:])
        return all(s.hasdata() for s in self.stores)

    def reset(self):
        self.si = 0
        for s in self.stores:
            s.reset()

    async def read(self):
        if self.order == 'sequential':
            while not self.stores[self.si].hasdata():
                self.si += 1
            return await self.stores[self.si].read()
        reads = [await s.read() for s in self.stores]
        return hjoin([r[0] for r in reads]), Cell.of_list([r[1] for r in reads], (1, len(reads)))

    async def readall(self):
        if self.order == 'sequential':
            return vjoin([await s.copy().readall() for s in self.stores])
        return await super().readall()

    def progress(self):
        if self.order == 'sequential':
            return float(sum(s.progress() for s in self.stores) / len(self.stores))
        return float(min(s.progress() for s in self.stores))

    def numpartitions(self):
        return float(min(s.numpartitions() for s in self.stores))

    def part_of(self, n, i):
        o = self.copy()
        o.stores = [s.part_of(n, i) for s in self.stores]
        return o

    def get(self, p):
        if p == 'UnderlyingDatastores':
            return Cell.of_list(list(self.stores), (1, len(self.stores)))
        if p == 'SupportedOutputFormats':
            return Str(np.array([['txt', 'csv', 'xlsx', 'png', 'jpg', 'tif', 'mat']], object))
        return super().get(p)


# ---- making them -----------------------------------------------------------------------------------------------------------

_TEXT_OPTS = ('includesubfolders', 'fileextensions', 'delimiter', 'numheaderlines', 'readvariablenames', 'variablenames',
              'selectedvariablenames', 'readsize', 'texttype', 'outputtype', 'type', 'variablenamingrule', 'fileencoding')
_SHEET_OPTS = ('includesubfolders', 'fileextensions', 'sheets', 'numheaderlines', 'readvariablenames', 'variablenames',
               'selectedvariablenames', 'readsize', 'texttype', 'outputtype', 'type', 'range')
_IMAGE_OPTS = ('includesubfolders', 'fileextensions', 'labelsource', 'labels', 'readsize', 'readfcn', 'type')
_FILE_OPTS = ('includesubfolders', 'fileextensions', 'readfcn', 'uniformread', 'readmode', 'blocksize', 'previewfcn', 'type')


def _set_common(ds, opts, fn):
    for key, prop in (('variablenames', 'VariableNames'), ('selectedvariablenames', 'SelectedVariableNames'),
                      ('readsize', 'ReadSize'), ('outputtype', 'OutputType')):
        if key in opts:
            ds.set(prop, opts[key])
    return ds


def make_text(location, opts, fn):
    sub = _flag(opts['includesubfolders'], fn, 'IncludeSubfolders') if 'includesubfolders' in opts else False
    exts = _exts_opt(opts['fileextensions'], fn) if 'fileextensions' in opts else TEXT_EXT
    files = find_files(location, fn, exts, sub)
    d = sval(opts['delimiter'], 'Delimiter', fn) if 'delimiter' in opts else None
    d = {'comma': ',', 'tab': '\t', '\\t': '\t', 'semi': ';', 'semicolon': ';', 'space': ' ', 'bar': '|'}.get(d, d)
    tt = (opt_str(opts['texttype']) or 'char').lower() if 'texttype' in opts else 'char'
    if tt not in ('char', 'string'):
        raise err(f'MATLAB:{fn}:InvalidTextType', "TextType is 'char' or 'string'.", fn)
    rule = (opt_str(opts['variablenamingrule']) or 'modify').lower() if 'variablenamingrule' in opts else 'modify'
    ds = TabularText(files, d, float(num(opts['numheaderlines'])) if 'numheaderlines' in opts else 0.0,
                     _flag(opts['readvariablenames'], fn, 'ReadVariableNames') if 'readvariablenames' in opts else True, tt, rule)
    return _set_common(ds, opts, fn)


def make_sheet(location, opts, fn):
    sub = _flag(opts['includesubfolders'], fn, 'IncludeSubfolders') if 'includesubfolders' in opts else False
    exts = _exts_opt(opts['fileextensions'], fn) if 'fileextensions' in opts else SHEET_EXT
    files = find_files(location, fn, exts, sub)
    tt = (opt_str(opts['texttype']) or 'char').lower() if 'texttype' in opts else 'char'
    ds = Spreadsheet(files, _sheets_value(opts['sheets']) if 'sheets' in opts else None,
                     float(num(opts['numheaderlines'])) if 'numheaderlines' in opts else 0.0,
                     _flag(opts['readvariablenames'], fn, 'ReadVariableNames') if 'readvariablenames' in opts else True, tt)
    return _set_common(ds, opts, fn)


def make_image(location, opts, fn):
    sub = _flag(opts['includesubfolders'], fn, 'IncludeSubfolders') if 'includesubfolders' in opts else False
    exts = _exts_opt(opts['fileextensions'], fn) if 'fileextensions' in opts else IMAGE_EXT
    files = find_files(location, fn, exts, sub)
    labels = None
    if 'labelsource' in opts:
        src = (opt_str(opts['labelsource']) or '').lower()
        if src == 'foldernames':
            labels = _folder_labels(files)
        elif src != 'none':
            raise err(f'MATLAB:{fn}:InvalidLabelSource', "LabelSource is 'foldernames' or 'none'.", fn)
    if 'labels' in opts:
        labels = _labels_value(opts['labels'], len(files))
    ds = ImageStore(files, labels)
    if 'readsize' in opts:
        ds.set('ReadSize', opts['readsize'])
    if 'readfcn' in opts:
        ds.set('ReadFcn', opts['readfcn'])
    return ds


def make_file(location, opts, fn):
    sub = _flag(opts['includesubfolders'], fn, 'IncludeSubfolders') if 'includesubfolders' in opts else False
    exts = _exts_opt(opts['fileextensions'], fn) if 'fileextensions' in opts else None
    files = find_files(location, fn, exts, sub)
    if 'readfcn' not in opts or not isinstance(opts['readfcn'], FH):
        raise err(f'MATLAB:{fn}:NoReadFcn', "A fileDatastore needs 'ReadFcn', a function handle that reads one file.", fn)
    mode = (opt_str(opts['readmode']) or 'file').lower() if 'readmode' in opts else 'file'
    if mode not in ('file', 'partialfile', 'bytes'):
        raise err(f'MATLAB:{fn}:InvalidReadMode', "ReadMode is 'file', 'partialfile' or 'bytes'.", fn)
    block = float(num(opts['blocksize'])) if 'blocksize' in opts else float('inf')
    if 'blocksize' in opts and mode == 'file':
        mode = 'bytes'
    if not block > 0:
        raise err(f'MATLAB:{fn}:InvalidBlockSize', 'BlockSize is a number of bytes from 1.', fn)
    return FileStore(files, opts['readfcn'], _flag(opts['uniformread'], fn, 'UniformRead') if 'uniformread' in opts else False,
                     mode, block, opts.get('previewfcn'))


def make_parquet(location, opts, fn):
    sub = _flag(opts['includesubfolders'], fn, 'IncludeSubfolders') if 'includesubfolders' in opts else False
    exts = _exts_opt(opts['fileextensions'], fn) if 'fileextensions' in opts else PARQUET_EXT
    files = find_files(location, fn, exts, sub)
    from .fileformats import parquet_names
    ds = ParquetStore(files, parquet_names(files[0]))
    return _set_common(ds, opts, fn)


def make_keyvalue(location, opts, fn):
    files = find_files(location, fn, ['.mat'], False)
    from .. import matfile as MF
    from .iofun import _fh_from_mat
    keys, values = [], []
    for p in files:
        try:
            vs, _ = MF.read(p, make_fh=_fh_from_mat)
        except MF.MatError as e:
            raise err(f'MATLAB:{fn}:NotKeyValue', f'{os.path.basename(p)} cannot be read: {e}.', fn)
        if 'Key' not in vs or 'Value' not in vs:
            raise err(f'MATLAB:{fn}:NotKeyValue', f'{os.path.basename(p)} holds no Key and Value variables.', fn)
        k, v = vs['Key'], vs['Value']
        ks = [py_str(x) if is_str(x) else float(np.asarray(darr(x)).reshape(-1)[0]) for x in (k.a.reshape(-1, order='F') if type(k) is Cell else np.asarray(darr(k), float).reshape(-1))]
        vals = list(v.a.reshape(-1, order='F')) if type(v) is Cell else [out(np.asarray(x).reshape(1, 1)) for x in np.asarray(darr(v)).reshape(-1)]
        keys += ks
        values += vals
    ds = KeyValueStore(keys, values, files)
    if 'readsize' in opts:
        ds.set('ReadSize', opts['readsize'])
    return ds


_KINDS = {'tabulartext': (make_text, _TEXT_OPTS), 'spreadsheet': (make_sheet, _SHEET_OPTS), 'image': (make_image, _IMAGE_OPTS),
          'file': (make_file, _FILE_OPTS), 'parquet': (make_parquet, ('includesubfolders', 'fileextensions', 'selectedvariablenames', 'readsize', 'outputtype', 'type')),
          'keyvalue': (make_keyvalue, ('readsize', 'type', 'includesubfolders', 'fileextensions'))}


def _kind_of(location, fn):
    """The kind of datastore the files call for (by their extensions)."""
    from .iofun import abspath
    items = _texts(location, fn)
    exts = set()
    for it in items:
        p = abspath(it)
        if os.path.isdir(p) and not any(c in it for c in '*?['):
            for f in _folder_files(p, None, False):
                exts.add(os.path.splitext(f)[1].lower())
        else:
            exts.add(os.path.splitext(it)[1].lower())
    for kind, known in (('tabulartext', TEXT_EXT), ('spreadsheet', SHEET_EXT), ('image', IMAGE_EXT), ('parquet', PARQUET_EXT), ('keyvalue', ['.mat'])):
        if exts and exts <= set(known):
            return kind
    for kind, known in (('tabulartext', TEXT_EXT), ('spreadsheet', SHEET_EXT), ('image', IMAGE_EXT), ('parquet', PARQUET_EXT), ('keyvalue', ['.mat'])):
        if exts & set(known):
            return kind
    raise err(f'MATLAB:{fn}:UnknownType', "The files are of no kind datastore knows: give 'Type' ('tabulartext', 'spreadsheet', 'image', 'file', 'parquet' or 'keyvalue').", fn)


@bi('datastore', aw=True, arr=False)
async def datastore(nargout, *args):
    """ds = datastore(location, Name, Value): a datastore of the kind the
    files' extensions call for, or of 'Type'."""
    nargchk(args, 1, 40, 'datastore')
    names = set(_TEXT_OPTS) | set(_SHEET_OPTS) | set(_IMAGE_OPTS) | set(_FILE_OPTS)
    pos, opts = _split(args, names, 'datastore')
    if len(pos) != 1:
        raise err('MATLAB:datastore:InvalidLocation', 'Give one location: a file, a folder, wildcards, or a list of them.', 'datastore')
    kind = (opt_str(opts['type']) or '').lower() if 'type' in opts else _kind_of(pos[0], 'datastore')
    if kind not in _KINDS:
        raise err('MATLAB:datastore:InvalidType', "Type is 'tabulartext', 'spreadsheet', 'image', 'file', 'parquet' or 'keyvalue'.", 'datastore')
    make, allowed = _KINDS[kind]
    bad = [k for k in opts if k not in allowed]
    if bad:
        raise err('MATLAB:datastore:InvalidParameter', f"'{bad[0]}' is not an option of a {kind} datastore.", 'datastore')
    if kind == 'parquet':
        from .fileformats import need_pyarrow
        await need_pyarrow('datastore')
    return make(pos[0], opts, 'datastore')


def _maker(fn, kind):
    make, allowed = _KINDS[kind]

    def f(nargout, *args):
        nargchk(args, 1, 40, fn)
        pos, opts = _split(args, allowed, fn)
        if len(pos) != 1:
            raise err(f'MATLAB:{fn}:InvalidLocation', 'Give one location: a file, a folder, wildcards, or a list of them.', fn)
        return make(pos[0], opts, fn)
    f.__name__ = fn
    return f


@bi('parquetDatastore', aw=True, arr=False)
async def parquetDatastore(nargout, *args):
    """pds = parquetDatastore(location, Name, Value): Parquet files read a file at a time (or ReadSize rows)."""
    from .fileformats import need_pyarrow
    await need_pyarrow('parquetDatastore')
    return _maker('parquetDatastore', 'parquet')(nargout, *args)


bi('tabularTextDatastore', arr=False)(_maker('tabularTextDatastore', 'tabulartext'))
bi('spreadsheetDatastore', arr=False)(_maker('spreadsheetDatastore', 'spreadsheet'))
bi('imageDatastore', arr=False)(_maker('imageDatastore', 'image'))
bi('fileDatastore', arr=False)(_maker('fileDatastore', 'file'))


@bi('arrayDatastore', arr=False)
def arrayDatastore(nargout, *args):
    """ads = arrayDatastore(A, 'ReadSize', n, 'IterationDimension', d,
    'OutputType', 'cell' or 'same'): an array read along a dimension."""
    nargchk(args, 1, 7, 'arrayDatastore')
    pos, opts = _split(args, ('readsize', 'iterationdimension', 'outputtype'), 'arrayDatastore')
    if len(pos) != 1:
        raise err('MATLAB:arrayDatastore:InvalidInput', 'Give the array, then Name, Value pairs.', 'arrayDatastore')
    dim = 1
    if 'iterationdimension' in opts:
        d = float(num(opts['iterationdimension']))
        if not (d >= 1 and d == int(d)):
            raise err('MATLAB:arrayDatastore:InvalidDimension', 'IterationDimension is a whole number from 1.', 'arrayDatastore')
        dim = int(d)
    ds = ArrayStore(pos[0], dim=dim)
    if 'readsize' in opts:
        ds.set('ReadSize', opts['readsize'])
    if 'outputtype' in opts:
        ds.set('OutputType', opts['outputtype'])
    return ds


# ---- the methods -----------------------------------------------------------------------------------------------------------------

def _ds(v, fn):
    if not isinstance(v, Datastore):
        raise err(f'MATLAB:{fn}:InvalidInput', f'{fn} takes a datastore.', fn)
    return v


def _take_over(name, test, handler, aw=False, nout=1):
    """name's builtin, with handler taking the calls whose first input passes
    test; a new builtin that takes only those when there is none."""
    info = REG.get(name)
    if info is None:
        if aw:
            async def f(nargout, *args):
                if not args or not test(args[0]):
                    raise err('MATLAB:UndefinedFunction', f"Undefined function '{name}' for input arguments of type '{class_of(args[0]) if args else 'none'}'.", name)
                return await handler(nargout, *args)
        else:
            def f(nargout, *args):
                if not args or not test(args[0]):
                    raise err('MATLAB:UndefinedFunction', f"Undefined function '{name}' for input arguments of type '{class_of(args[0]) if args else 'none'}'.", name)
                return handler(nargout, *args)
        f.__doc__ = handler.__doc__
        REG[name] = Info(name, f, False, aw, nout, False)
        return
    orig, ws, was_aw = info.fn, info.ws, info.aw
    if aw or was_aw:
        async def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                r = handler(a[1] if ws else a[0], *args)
                return (await r) if aw else r
            r = orig(*a)
            return (await r) if was_aw else r
    else:
        def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                return handler(a[1] if ws else a[0], *args)
            return orig(*a)
    REG[name] = Info(name, f, ws, aw or was_aw, max(nout, info.nout), False)


def _is_ds(v):
    return isinstance(v, Datastore)


async def _read(nargout, *args):
    """[data, info] = read(ds): the next block."""
    nargchk(args, 1, 1, 'read')
    data, info = await args[0].read()
    return (data, info) if nargout > 1 else data


async def _readall(nargout, *args):
    """data = readall(ds): everything, from the start."""
    nargchk(args, 1, 3, 'readall')
    return await args[0].readall()


def _hasdata(nargout, *args):
    nargchk(args, 1, 1, 'hasdata')
    return bool(args[0].hasdata())


def _reset(nargout, *args):
    nargchk(args, 1, 1, 'reset')
    args[0].reset()
    return None


async def _preview(nargout, *args):
    nargchk(args, 1, 1, 'preview')
    return await args[0].preview()


def _progress(nargout, *args):
    nargchk(args, 1, 1, 'progress')
    return args[0].progress()


def _numpartitions(nargout, *args):
    nargchk(args, 1, 2, 'numpartitions')
    n = args[0].numpartitions()
    if len(args) > 1:
        # numpartitions(ds, pool): no more than the pool has workers, and the files
        pool = args[1]
        w = float(num(pool.getprop('NumWorkers'))) if isinstance(pool, Obj) else float(num(pool))
        n = float(min(n, max(1.0, w)))
    return n


def _partition(nargout, *args):
    nargchk(args, 3, 3, 'partition')
    ds = args[0]
    if is_str(args[1]):
        how = py_str(args[1]).lower()
        if how != 'files' or not ds.file_based:
            raise err('MATLAB:partition:InvalidType', "partition(ds, 'Files', k) takes a datastore of files.", 'partition')
        if is_str(args[2]):
            from .iofun import abspath
            p = abspath(py_str(args[2]))
            if p not in ds.files:
                raise err('MATLAB:partition:FileNotFound', f"'{py_str(args[2])}' is not one of the datastore's files.", 'partition')
            return ds.with_files([ds.files.index(p)])
        k = float(num(args[2]))
        if not (1 <= k <= len(ds.files) and k == int(k)):
            raise err('MATLAB:partition:InvalidIndex', f'The file index is a whole number from 1 to {len(ds.files)}.', 'partition')
        return ds.with_files([int(k) - 1])
    n, i = float(num(args[1])), float(num(args[2]))
    if not (n >= 1 and n == int(n)):
        raise err('MATLAB:partition:InvalidNumPartitions', 'The number of partitions is a whole number from 1.', 'partition')
    if not (1 <= i <= n and i == int(i)):
        raise err('MATLAB:partition:InvalidIndex', f'The partition index is a whole number from 1 to {int(n)}.', 'partition')
    return ds.part_of(int(n), int(i) - 1)


def _shuffle(nargout, *args):
    nargchk(args, 1, 1, 'shuffle')
    from .elmat import RNG
    ds = args[0]
    if isinstance(ds, ArrayStore):
        return ds.with_rows(list(RNG.rs.permutation(ds.count())))
    if isinstance(ds, KeyValueStore):
        o = ds.copy()
        p = RNG.rs.permutation(len(ds.keys))
        o.keys, o.values, o.k = [ds.keys[i] for i in p], [ds.values[i] for i in p], 0
        return o
    if isinstance(ds, (Transformed, Combined)):
        raise err('MATLAB:shuffle:NotShuffleable', 'This datastore cannot be shuffled: shuffle the datastores under it.', 'shuffle')
    return ds.with_files(list(RNG.rs.permutation(len(ds.files))))


def _subset(nargout, *args):
    nargchk(args, 2, 2, 'subset')
    ds = args[0]
    v = args[1]
    n = ds.count() if isinstance(ds, ArrayStore) else len(ds.keys) if isinstance(ds, KeyValueStore) else len(ds.files)
    a = np.asarray(darr(v)).reshape(-1)
    if a.dtype == bool:
        if a.size != n:
            raise err('MATLAB:subset:InvalidIndices', f'A logical index has {n} elements.', 'subset')
        idx = list(np.flatnonzero(a))
    else:
        a = a.astype(float)
        if np.any(a < 1) or np.any(a > n) or np.any(a != np.round(a)):
            raise err('MATLAB:subset:InvalidIndices', f'The indices are whole numbers from 1 to {n}.', 'subset')
        idx = [int(x) - 1 for x in a]
    if isinstance(ds, ArrayStore):
        return ds.with_rows(idx)
    if isinstance(ds, KeyValueStore):
        o = ds.copy()
        o.keys, o.values, o.k = [ds.keys[i] for i in idx], [ds.values[i] for i in idx], 0
        return o
    if not ds.file_based:
        raise err('MATLAB:subset:NotSubsettable', 'subset takes a datastore of files or an arrayDatastore.', 'subset')
    return ds.with_files(idx)


def _transform(nargout, *args):
    """dsnew = transform(ds, @fcn), transform(ds1, ds2, ..., @fcn), with 'IncludeInfo', true."""
    nargchk(args, 2, 40, 'transform')
    rest = list(args)
    inc = False
    if len(rest) >= 3 and is_str(rest[-2]) and py_str(rest[-2]).lower() == 'includeinfo':
        inc = _flag(rest[-1], 'transform', 'IncludeInfo')
        rest = rest[:-2]
    f = rest[-1]
    stores = rest[:-1]
    if not isinstance(f, FH):
        raise err('MATLAB:transform:InvalidFunction', 'The last input (before the options) is a function handle.', 'transform')
    if not stores or not all(isinstance(s, Datastore) for s in stores):
        raise err('MATLAB:transform:InvalidInput', 'transform takes datastores, then a function handle.', 'transform')
    if len(stores) == 1 and isinstance(stores[0], Transformed) and len(stores[0].stores) >= 1:
        o = stores[0].copy()
        inc0 = o.include if isinstance(o.include, list) else [o.include] * len(o.fns)
        o.fns = list(o.fns) + [f]
        o.include = inc0 + [inc]
        return o
    return Transformed([_fresh(s) for s in stores], [f], [inc])


def _fresh(ds):
    """A copy of a datastore at its start, for a datastore made over it."""
    c = ds.copy()
    c.reset()
    return c


def _combine(nargout, *args):
    """dsnew = combine(ds1, ds2, ..., 'ReadOrder', 'associated' or 'sequential')."""
    nargchk(args, 1, 40, 'combine')
    rest = list(args)
    order = 'associated'
    if len(rest) >= 3 and is_str(rest[-2]) and py_str(rest[-2]).lower() == 'readorder':
        order = py_str(rest[-1]).lower()
        if order not in ('associated', 'sequential'):
            raise err('MATLAB:combine:InvalidReadOrder', "ReadOrder is 'associated' or 'sequential'.", 'combine')
        rest = rest[:-2]
    if not all(isinstance(s, Datastore) for s in rest):
        raise err('MATLAB:combine:InvalidInput', 'combine takes datastores.', 'combine')
    return Combined([_fresh(s) for s in rest], order)


def _is_part(nargout, *args):
    nargchk(args, 1, 1, 'isPartitionable')
    return True


def _is_shuf(nargout, *args):
    nargchk(args, 1, 1, 'isShuffleable')
    return not isinstance(args[0], (Transformed, Combined))


def _count_labels(nargout, *args):
    """tbl = countEachLabel(imds): how many images each label has."""
    nargchk(args, 1, 1, 'countEachLabel')
    ds = args[0]
    from .tables import Table
    from .categoricals import Categorical
    lab = ds.labels
    if lab is None:
        raise err('MATLAB:countEachLabel:NoLabels', 'The datastore has no labels.', 'countEachLabel')
    if isinstance(lab, Categorical):
        cats = list(lab.cats)
        counts = [float(np.sum(lab.a == k + 1)) for k in range(len(cats))]
        keep = [k for k in range(len(cats)) if counts[k] > 0]
        L = Categorical(np.array([[k + 1.0] for k in keep]).reshape(-1, 1), cats)
        return Table([L, np.array([[counts[k]] for k in keep]).reshape(-1, 1)], ['Label', 'Count'])
    vals = [py_str(x) if is_str(x) else float(np.asarray(darr(x)).reshape(-1)[0]) for x in (lab.a.reshape(-1, order='F') if type(lab) in (Cell,) else (lab.a.reshape(-1, order='F') if type(lab) is Str else np.asarray(darr(lab)).reshape(-1)))]
    uniq = sorted(set(vals), key=lambda x: (isinstance(x, str), x))
    counts = np.array([[float(vals.count(u))] for u in uniq]).reshape(-1, 1)
    if all(isinstance(u, str) for u in uniq):
        key = Cell.of_list([Char.of(u) for u in uniq], (len(uniq), 1))
    else:
        key = np.array([[u] for u in uniq], float).reshape(-1, 1)
    return Table([key, counts], ['Label', 'Count'])


def _split_labels(nargout, *args):
    """[ds1, ..., dsM] = splitEachLabel(imds, p1, ..., 'randomized'): each
    label's files split by proportions (or counts), in order unless randomized."""
    nargchk(args, 2, 20, 'splitEachLabel')
    ds = args[0]
    rest = list(args[1:])
    random = False
    if rest and is_str(rest[-1]) and py_str(rest[-1]).lower() in ('randomized', 'randomize'):
        random = True
        rest = rest[:-1]
    shares = [float(num(r)) for r in rest]
    if not shares or any(s < 0 for s in shares):
        raise err('MATLAB:splitEachLabel:InvalidProportions', 'Give proportions (below 1, adding up to at most 1) or numbers of files.', 'splitEachLabel')
    if ds.labels is None:
        raise err('MATLAB:splitEachLabel:NoLabels', 'The datastore has no labels.', 'splitEachLabel')
    from .categoricals import Categorical
    lab = ds.labels
    keys = list(lab.names().reshape(-1)) if isinstance(lab, Categorical) else [str(x) for x in (np.asarray(lab.elem_strings() if hasattr(lab, 'elem_strings') else [py_str(c) if is_str(c) else str(float(np.asarray(darr(c)).reshape(-1)[0])) for c in lab.a.reshape(-1, order='F')], object).reshape(-1))]
    groups = {}
    for i, k in enumerate(keys):
        groups.setdefault(k, []).append(i)
    from .elmat import RNG
    parts = [[] for _ in range(len(shares) + 1)]
    for k in sorted(groups):
        idx = groups[k]
        if random:
            idx = [idx[j] for j in RNG.rs.permutation(len(idx))]
        n = len(idx)
        start = 0
        for j, s in enumerate(shares):
            # below 1 a proportion of the label's files (rounded), else a number of them
            take = int(math.floor(s * n + 0.5)) if s < 1 else int(s)
            take = min(take, n - start)
            parts[j] += idx[start:start + take]
            start += take
        parts[-1] += idx[start:]
    outs = [ds.with_files(sorted(p)) for p in parts]
    n = max(nargout, 1)
    return tuple(outs[:n]) if n > 1 else outs[0]


async def _writeall(nargout, *args):
    """writeall(ds, folder, 'OutputFormat', fmt, 'FilenamePrefix', p,
    'FilenameSuffix', s, 'FolderLayout', 'duplicate' or 'flatten'): each
    file's data written again, as text, a spreadsheet, an image or a
    MAT-file."""
    nargchk(args, 2, 12, 'writeall')
    ds = args[0]
    folder = sval(args[1], 'output folder', 'writeall')
    pos, opts = _split(args[2:], ('outputformat', 'filenameprefix', 'filenamesuffix', 'folderlayout', 'usetextuallyformattedfilename'), 'writeall')
    from .iofun import abspath, files_changed
    dest = abspath(folder)
    if not ds.file_based or not ds.files:
        raise err('MATLAB:writeall:NotFileBased', 'writeall takes a datastore of files.', 'writeall')
    fmt = (opt_str(opts['outputformat']) or '').lower().lstrip('.') if 'outputformat' in opts else None
    prefix = sval(opts['filenameprefix'], 'FilenamePrefix', 'writeall') if 'filenameprefix' in opts else ''
    suffix = sval(opts['filenamesuffix'], 'FilenameSuffix', 'writeall') if 'filenamesuffix' in opts else ''
    flat = (opt_str(opts['folderlayout']) or 'duplicate').lower() == 'flatten' if 'folderlayout' in opts else False
    root = os.path.commonpath([os.path.dirname(f) for f in ds.files])
    written = []
    for i, p in enumerate(ds.files):
        one = ds.with_files([i])
        data = await one.readall()
        if isinstance(ds, ImageStore):
            data = data.a.reshape(-1)[0]
        base, ext = os.path.splitext(os.path.basename(p))
        ext = '.' + fmt if fmt else ext
        sub = '' if flat else os.path.relpath(os.path.dirname(p), root)
        target = os.path.normpath(os.path.join(dest, sub, prefix + base + suffix + ext))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        from .tables import Table
        if isinstance(data, Table):
            REG['writetable'].fn(0, data, Char.of(target))
        elif ext.lower() == '.mat':
            await _save_vars(target, {'data': data})
        elif isinstance(ds, ImageStore) or ext.lower() in IMAGE_EXT:
            r = REG['imwrite'].fn(0, data, Char.of(target))
            if REG['imwrite'].aw:
                await r
        else:
            raise err('MATLAB:writeall:UnknownFormat', f"Data of class {class_of(data)} is written as a table, an image or a MAT-file: give 'OutputFormat'.", 'writeall')
        written.append(target)
    files_changed(dest)
    return None


async def _readimage(nargout, *args):
    """[img, info] = readimage(imds, k): the k-th image, read as the datastore reads (its ReadFcn), without moving it."""
    nargchk(args, 2, 2, 'readimage')
    ds = args[0]
    if not isinstance(ds, ImageStore):
        raise err('MATLAB:readimage:NotImageDatastore', 'readimage reads an image of an imageDatastore.', 'readimage')
    k, n = float(num(args[1])), len(ds.files)
    if not (k == int(k) and 1 <= k <= n):
        raise err('MATLAB:readimage:InvalidIndex', f'The index is a whole number from 1 to {n}, the number of files.', 'readimage')
    i = int(k) - 1
    img = await ds.read_file(ds.files[i])
    if nargout < 2:
        return img
    d = {'Filename': Char.of(ds.files[i]), 'FileSize': _size_of(ds.files[i])}
    lab = ds._labels_at([i])
    if lab is not None:
        d['Label'] = lab
    return img, Struct.scalar(d)


def _copy_ds(nargout, *args):
    nargchk(args, 1, 1, 'copy')
    return args[0].copy()


for _name, _h, _aw, _nout in (('read', _read, True, 2), ('readall', _readall, True, 1), ('hasdata', _hasdata, False, 1),
                              ('reset', _reset, False, 1), ('preview', _preview, True, 1), ('progress', _progress, False, 1),
                              ('numpartitions', _numpartitions, False, 1), ('partition', _partition, False, 1),
                              ('shuffle', _shuffle, False, 1), ('subset', _subset, False, 1), ('transform', _transform, False, 1),
                              ('combine', _combine, False, 1), ('isPartitionable', _is_part, False, 1), ('isShuffleable', _is_shuf, False, 1),
                              ('countEachLabel', _count_labels, False, 1), ('splitEachLabel', _split_labels, False, 8),
                              ('writeall', _writeall, True, 1), ('readimage', _readimage, True, 2)):
    _take_over(_name, _is_ds, _h, _aw, _nout)


COPY_HANDLERS = [(_is_ds, _copy_ds)]       # copy: classfun asks these first


# ---- mapreduce ---------------------------------------------------------------------------------------------------------------

class KVStore(Obj):
    """The store a map or reduce function adds keys and values to."""
    is_handle = True
    cls = 'matlab.mapreduce.KeyValueStore'

    def __init__(self):
        self.order = []
        self.vals = {}

    def value_copy(self):
        return self

    def add(self, key, value):
        k = _key(key)
        if k not in self.vals:
            self.order.append(k)
            self.vals[k] = []
        self.vals[k].append(value)

    def getprop(self, name):
        if name.lower() in ('add', 'addmulti'):
            from ..classdef import BoundBuiltin
            return BoundBuiltin(self, name.lower())
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{self.cls}'.")

    def propnames(self):
        return []

    def display_lines(self):
        return [f'  KeyValueStore holding {len(self.order)} keys']


def _key(v):
    """A key: text, or a real number."""
    if is_str(v):
        return py_str(v)
    a = np.asarray(darr(v)).reshape(-1)
    if a.size != 1 or a.dtype.kind not in 'biuf' or not np.isfinite(float(a[0])):
        raise err('MATLAB:mapreduce:InvalidKey', 'A key is text or one real number.', 'add')
    return float(a[0])


class ValueIter(Obj):
    """The values of one key, for a reduce function: hasnext and getnext."""
    is_handle = True
    cls = 'matlab.mapreduce.ValueIterator'

    def __init__(self, key, vals):
        self.key, self.vals, self.k = key, vals, 0

    def value_copy(self):
        return self

    def getprop(self, name):
        if name.lower() == 'key':
            return Char.of(self.key) if isinstance(self.key, str) else self.key
        if name.lower() in ('hasnext', 'getnext'):
            from ..classdef import BoundBuiltin
            return BoundBuiltin(self, name.lower())
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{self.cls}'.")

    def propnames(self):
        return ['Key']

    def display_lines(self):
        return [f'  ValueIterator of key {self.key!r}: {len(self.vals) - self.k} values left']


def _add(nargout, *args):
    nargchk(args, 3, 3, 'add')
    args[0].add(args[1], args[2])
    return None


def _addmulti(nargout, *args):
    nargchk(args, 3, 3, 'addmulti')
    S, keys, vals = args
    if type(keys) is Cell or type(keys) is Str:
        ks = [x for x in (keys.a.reshape(-1, order='F'))]
        ks = [Char.of(x) if isinstance(x, str) else x for x in ks]
    else:
        ks = [float(x) for x in np.asarray(darr(keys)).reshape(-1, order='F')]
    if type(vals) is not Cell:
        raise err('MATLAB:mapreduce:InvalidValues', 'addmulti takes the values as a cell array, one for each key.', 'addmulti')
    vs = list(vals.a.reshape(-1, order='F'))
    if len(vs) != len(ks):
        raise err('MATLAB:mapreduce:InvalidValues', f'There are {len(ks)} keys and {len(vs)} values.', 'addmulti')
    for k, v in zip(ks, vs):
        S.add(k, v)
    return None


def _hasnext(nargout, *args):
    nargchk(args, 1, 1, 'hasnext')
    it = args[0]
    return it.k < len(it.vals)


def _getnext(nargout, *args):
    nargchk(args, 1, 1, 'getnext')
    it = args[0]
    if it.k >= len(it.vals):
        raise err('MATLAB:mapreduce:NoMoreValues', 'There are no more values: check hasnext first.', 'getnext')
    v = it.vals[it.k]
    it.k += 1
    return v


_take_over('add', lambda v: isinstance(v, KVStore), _add)
_take_over('addmulti', lambda v: isinstance(v, KVStore), _addmulti)
_take_over('hasnext', lambda v: isinstance(v, ValueIter), _hasnext)
_take_over('getnext', lambda v: isinstance(v, ValueIter), _getnext)


@bi('mapreduce', aw=True, arr=False)
async def mapreduce(nargout, *args):
    """outds = mapreduce(ds, mapfun, reducefun, Name, Value): mapfun(data,
    info, store) on each block the datastore reads, then reducefun(key,
    values, store) on each key's values; the keys and values the reduce
    function adds, as a KeyValueDatastore. 'OutputFolder' also writes them
    to a MAT-file there; 'Display' 'off' leaves out the progress."""
    nargchk(args, 3, 12, 'mapreduce')
    ds, mapfun, redfun = args[0], args[1], args[2]
    rest = list(args[3:])
    if rest and not is_str(rest[0]):
        rest = rest[1:]                 # a mapreducer: this engine has one way to run
    pos, opts = _split(rest, ('outputfolder', 'outputtype', 'display'), 'mapreduce')
    if not isinstance(ds, Datastore):
        raise err('MATLAB:mapreduce:InvalidDatastore', 'The first input is a datastore.', 'mapreduce')
    if not isinstance(mapfun, FH) or not isinstance(redfun, FH):
        raise err('MATLAB:mapreduce:InvalidFunction', 'The map and reduce functions are function handles.', 'mapreduce')
    show = _flag(opts['display'], 'mapreduce', 'Display') if 'display' in opts else True
    if 'outputtype' in opts and (opt_str(opts['outputtype']) or '').lower() not in ('binary',):
        raise err('MATLAB:mapreduce:InvalidOutputType', "OutputType is 'Binary' here (a KeyValueDatastore).", 'mapreduce')
    src = ds.copy()
    src.reset()
    inter = KVStore()
    if show:
        R.write('Map   0% Reduce   0%\n')
    last = 0
    while src.hasdata():
        data, info = await src.read()
        await mapfun.acall(0, data, info, inter)
        pc = int(100 * src.progress())
        if show and pc >= last + 25 and pc < 100:
            R.write(f'Map {pc:3d}% Reduce   0%\n')
            last = pc
    if show:
        R.write('Map 100% Reduce   0%\n')
    result = KVStore()
    n = len(inter.order)
    last = 0
    for i, k in enumerate(inter.order):
        it = ValueIter(k, inter.vals[k])
        await redfun.acall(0, Char.of(k) if isinstance(k, str) else k, it, result)
        pc = int(100 * (i + 1) / n)
        if show and pc >= last + 25 and pc < 100:
            R.write(f'Map 100% Reduce {pc:3d}%\n')
            last = pc
    if show:
        R.write('Map 100% Reduce 100%\n')
    keys, vals = [], []
    for k in result.order:
        for v in result.vals[k]:
            keys.append(k)
            vals.append(v)
    files = None
    if 'outputfolder' in opts:
        from .iofun import abspath, files_changed
        folder = abspath(sval(opts['outputfolder'], 'OutputFolder', 'mapreduce'))
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, 'results_1.mat')
        kk = Cell.of_list([Char.of(k) if isinstance(k, str) else k for k in keys], (len(keys), 1))
        await _save_vars(target, {'Key': kk, 'Value': Cell.of_list(vals, (len(vals), 1))})
        files_changed(folder)
        files = [target]
    return KeyValueStore(keys, vals, files)


def classes():
    return (Datastore, KVStore, ValueIter)
