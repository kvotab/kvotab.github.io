"""Import options and XML documents: detectImportOptions, setvartype,
setvaropts, getvaropts and readvars (readtable, readmatrix and readcell take
the options); xmlread, xmlwrite and com.mathworks.xml.XMLUtils.createDocument,
whose document objects answer the Document Object Model's methods
(getDocumentElement, getElementsByTagName, getAttribute, item, getLength,
appendChild and the rest) through Python's xml.dom.minidom."""
import copy
import os

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, out, num, opt_str, is_str, darr
from ..values import MError, Obj, Char, Cell, Struct, Str, EMPTY, numel, py_str, text_list
from .. import runtime as R


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, KeyError, OSError) as e:
                raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _cellrow(items):
    return Cell.of_list([Char.of(s) for s in items])


def _list(v):
    if isinstance(v, (Cell, Str)) or (isinstance(v, Char) and v.a.shape[0] > 1):
        return text_list(v)
    return [py_str(v)]


# ---- import options ---------------------------------------------------------------------------------------------------------------

class ImportOptions(Obj):
    is_handle = False

    def __init__(self, kind, names, types, data_start, names_line, delimiter=',', sheet=''):
        self.kind = kind            # 'text' or 'spreadsheet'
        self.names = list(names)
        self.types = list(types)
        self.selected = list(names)
        self.data = [float(data_start), float('inf')]
        self.names_line = float(names_line)
        self.delimiter = delimiter
        self.sheet = sheet
        self.varopts = {}
        self.missing_rule = 'fill'
        self.error_rule = 'fill'

    @property
    def cls(self):
        return 'matlab.io.text.DelimitedTextImportOptions' if self.kind == 'text' else 'matlab.io.spreadsheet.SpreadsheetImportOptions'

    def value_copy(self):
        return copy.deepcopy(self)

    def props(self):
        d = {}
        if self.kind == 'text':
            d['Delimiter'] = _cellrow([self.delimiter])
        else:
            d['Sheet'] = Char.of(self.sheet)
        d.update({'MissingRule': Char.of(self.missing_rule), 'ImportErrorRule': Char.of(self.error_rule),
                  'VariableNames': _cellrow(self.names), 'VariableTypes': _cellrow(self.types), 'SelectedVariableNames': _cellrow(self.selected)})
        if self.kind == 'text':
            d['DataLines'] = np.array([self.data])
            d['VariableNamesLine'] = self.names_line
        else:
            d['DataRange'] = Char.of(f'A{int(self.data[0])}')
            d['VariableNamesRange'] = Char.of(f'A{int(self.names_line)}' if self.names_line else '')
        return d

    def getprop(self, name):
        for k, v in self.props().items():
            if k.lower() == name.lower():
                return v
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class '{self.cls.split('.')[-1]}'.")

    def setprop(self, name, value):
        n = name.lower()
        if n == 'variablenames':
            new = _list(value)
            if len(new) != len(self.names):
                raise MError('MATLAB:textio:io:VariableNamesSize', f'VariableNames has {len(self.names)} names.')
            mapping = dict(zip(self.names, new))
            self.selected = [mapping.get(s, s) for s in self.selected]
            self.names = new
        elif n == 'variabletypes':
            new = _list(value)
            if len(new) != len(self.types):
                raise MError('MATLAB:textio:io:VariableTypesSize', f'VariableTypes has {len(self.types)} types.')
            self.types = new
        elif n == 'selectedvariablenames':
            sel = _list(value) if not isinstance(value, np.ndarray) else [self.names[int(k) - 1] for k in np.asarray(value).reshape(-1)]
            bad = [s for s in sel if s not in self.names]
            if bad:
                raise MError('MATLAB:textio:io:UnknownVarName', f"'{bad[0]}' is not one of the VariableNames.")
            self.selected = sel
        elif n == 'datalines':
            v = darr(value).reshape(-1)
            self.data = [float(v[0]), float(v[1]) if v.size > 1 else float('inf')]
        elif n == 'datarange':
            import re
            m = re.match(r'[A-Za-z]*(\d+)', py_str(value))
            self.data = [float(m.group(1)) if m else 1.0, float('inf')]
        elif n in ('variablenamesline', 'variablenamesrange'):
            if is_str(value):
                import re
                m = re.match(r'[A-Za-z]*(\d+)', py_str(value))
                self.names_line = float(m.group(1)) if m else 0.0
            else:
                self.names_line = float(num(value))
        elif n == 'delimiter':
            self.delimiter = _list(value)[0]
        elif n == 'sheet':
            self.sheet = py_str(value) if is_str(value) else str(int(num(value)))
        elif n == 'missingrule':
            self.missing_rule = py_str(value).lower()
        elif n == 'importerrorrule':
            self.error_rule = py_str(value).lower()
        else:
            raise MError('MATLAB:noPublicFieldForClass', f"Unrecognized property '{name}' for class '{self.cls.split('.')[-1]}'.")

    def propnames(self):
        return list(self.props())

    def display_lines(self):
        from ..display import summary
        d = self.props()
        w = max(len(k) for k in d)
        lines = [f'  {self.cls.split(".")[-1]} with properties:', '']
        for k, v in d.items():
            if k == 'VariableNames':
                lines += ['', '   Variable Import Properties: Set types by name using setvartype']
            if k in ('DataLines', 'DataRange'):
                lines += ['', '   Location Properties:']
            shown = summary(v) if not isinstance(v, Cell) or v.a.size > 6 else '{' + ', '.join("'" + x.str() + "'" for x in v.a.reshape(-1)) + '}'
            lines.append(f'    {k.rjust(w)}: {shown}')
        return lines


def _kind_of(v):
    from .timetypes import DateTime, Duration
    from .categoricals import Categorical
    if isinstance(v, DateTime):
        return 'datetime'
    if isinstance(v, Duration):
        return 'duration'
    if isinstance(v, Categorical):
        return 'categorical'
    if isinstance(v, Str):
        return 'string'
    if isinstance(v, Cell):
        return 'char'
    a = np.asarray(v)
    return 'logical' if a.dtype == bool else 'double'


@bi('detectImportOptions')
def detectImportOptions(nargout, *args):
    """opts = detectImportOptions(filename, Name, Value): how readtable would read a text file or spreadsheet: the variables' names and types, where the data lines are."""
    nargchk(args, 1, 15, 'detectImportOptions')
    from .iofun import _existing
    p = _existing(args[0], 'detectImportOptions')
    ext = os.path.splitext(p)[1].lower()
    o = {}
    for i in range(1, len(args) - 1, 2):
        o[py_str(args[i]).lower()] = args[i + 1]
    skip = int(num(o.get('numheaderlines', 0.0)))
    readnames = bool(num(o['readvariablenames'])) if 'readvariablenames' in o else True
    kind = 'spreadsheet' if ext in ('.xlsx', '.xlsm') or py_str(o.get('filetype', Char.of(''))).lower() == 'spreadsheet' else 'text'
    delim = py_str(o['delimiter']) if 'delimiter' in o else ','
    extra = []
    if kind == 'text' and 'delimiter' not in o:
        # the delimiter: the most frequent of , tab ; | in the first line after the header lines
        with open(p, encoding='utf-8', errors='replace') as f:
            lines = [ln for ln in f.read().split('\n')[skip:] if ln.strip()]
        head = lines[0] if lines else ''
        delim = max([',', '\t', ';', '|'], key=lambda d: head.count(d)) if any(c in head for c in ',\t;|') else ' '
        extra = [Char.of('Delimiter'), Char.of(delim)]
    T = R._builtin('readtable', *args, *extra)
    names_line = (skip + 1) if readnames else 0
    io = ImportOptions(kind, T.names, [_kind_of(v) for v in T.vars], names_line + 1, names_line, delim,
                       py_str(o['sheet']) if 'sheet' in o and is_str(o['sheet']) else '')
    return io


def _opts_of(v, fn):
    if not isinstance(v, ImportOptions):
        raise err(f'MATLAB:{fn}:opts', f'{fn} takes import options (from detectImportOptions).', fn)
    return v


def _vars(io, v):
    if isinstance(v, np.ndarray) or isinstance(v, float):
        return [io.names[int(k) - 1] for k in np.asarray(v).reshape(-1)]
    names = _list(v)
    for n in names:
        if n not in io.names:
            raise err('MATLAB:textio:io:UnknownVarName', f"'{n}' is not one of the VariableNames.", 'setvartype')
    return names


_TYPES = ('double', 'single', 'int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32', 'uint64', 'logical', 'char', 'string',
          'categorical', 'datetime', 'duration')


@bi('setvartype')
def setvartype(nargout, *args):
    """opts = setvartype(opts, type), setvartype(opts, vars, type): the types the variables are read as."""
    nargchk(args, 2, 3, 'setvartype')
    io = _opts_of(args[0], 'setvartype').value_copy()
    vars_ = io.names if len(args) == 2 else _vars(io, args[1])
    types = _list(args[-1])
    for t in types:
        if t not in _TYPES:
            raise err('MATLAB:setvartype:type', f"'{t}' is not a type here: one of {', '.join(_TYPES)}.", 'setvartype')
    for i, v in enumerate(vars_):
        io.types[io.names.index(v)] = types[i] if len(types) == len(vars_) else types[0]
    return io


@bi('setvaropts')
def setvaropts(nargout, *args):
    """opts = setvaropts(opts, vars, Name, Value): options of variables: FillValue, TreatAsMissing, InputFormat (datetime), Categories, TrimNonNumeric, ..."""
    nargchk(args, 3, 20, 'setvaropts')
    io = _opts_of(args[0], 'setvaropts').value_copy()
    rest = list(args[1:])
    vars_ = io.names
    if len(rest) % 2 == 1:
        vars_ = _vars(io, rest.pop(0))
    for i in range(0, len(rest), 2):
        k = py_str(rest[i])
        for v in vars_:
            io.varopts.setdefault(v, {})[k.lower()] = (k, rest[i + 1])
    return io


@bi('getvaropts')
def getvaropts(nargout, *args):
    """vopts = getvaropts(opts, var): a variable's import options, as a struct."""
    nargchk(args, 2, 2, 'getvaropts')
    io = _opts_of(args[0], 'getvaropts')
    v = _vars(io, args[1])[0]
    d = {'Name': Char.of(v), 'Type': Char.of(io.types[io.names.index(v)])}
    for k, (orig, val) in io.varopts.get(v, {}).items():
        d[orig] = val
    if 'FillValue' not in d and d['Type'].str() in ('double', 'single'):
        d['FillValue'] = np.nan
    return Struct.scalar(d)


def _convert(v, t, vo):
    from .timetypes import DateTime
    kind = _kind_of(v)
    if t == kind:
        return v
    if t in ('double', 'single', 'int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32', 'uint64', 'logical'):
        if kind in ('char', 'string'):
            v = R._builtin('str2double', v)
        r = R._builtin(t, v)
        return r
    if t == 'string':
        return R._builtin('string', v)
    if t == 'char':
        return R._builtin('cellstr', R._builtin('string', v))
    if t == 'categorical':
        return R._builtin('categorical', v)
    if t == 'datetime':
        if 'inputformat' in vo:
            return R._builtin('datetime', v, Char.of('InputFormat'), vo['inputformat'][1])
        return R._builtin('datetime', v)
    if t == 'duration':
        return R._builtin('duration', v)
    return v


def _fill(v, vo):
    if 'fillvalue' in vo and isinstance(v, np.ndarray) and v.dtype.kind == 'f':
        fv = float(num(vo['fillvalue'][1]))
        return np.where(np.isnan(v), fv, v)
    return v


def _raw_column(path, io, k, base, rows):
    """Column k of a text file's data rows as written (base: the file's row of the table's first; blank lines skipped),
    for a variable read as text whose values look like numbers ('007' stays '007')."""
    import csv
    with open(path, newline='', encoding='utf-8-sig') as f:
        lines = [r for r in csv.reader(f, delimiter=io.delimiter or ',')]
    head, body = lines[:base], [r for r in lines[base:] if any(c.strip() for c in r)]
    del head
    return [body[r][k].strip() if r < len(body) and k < len(body[r]) else '' for r in rows]


def _read_with(path, io):
    """The table the import options read: the rows from DataLines, the variables renamed, typed and selected."""
    from .tables import Table, _take_rows
    base = []
    if io.kind == 'text':
        base += [Char.of('Delimiter'), Char.of(io.delimiter)]
    elif io.sheet:
        base += [Char.of('Sheet'), Char.of(io.sheet)]
    readnames = io.names_line > 0
    header = int(io.names_line - 1) if readnames else int(io.data[0] - 1)
    T = R._builtin('readtable', Char.of(path), Char.of('NumHeaderLines'), float(max(header, 0)), Char.of('ReadVariableNames'), readnames, *base)
    first_data = int(io.data[0]) - (int(io.names_line) + 1 if readnames else int(io.data[0]))
    last = io.data[1]
    rows = list(range(max(first_data, 0), T.n if not np.isfinite(last) else min(T.n, int(last) - int(io.data[0]) + 1 + max(first_data, 0))))
    vars_ = []
    names = []
    for k, (orig, newname) in enumerate(zip(T.names, io.names)):
        if newname not in io.selected:
            continue
        v = _take_rows(T.vars[k], rows) if len(rows) != T.n else T.vars[k]
        if io.kind == 'text' and io.types[k] in ('string', 'char', 'categorical', 'datetime', 'duration') and _kind_of(v) in ('double', 'logical'):
            # read as numbers but wanted as text: the text as the file has it
            raw = _raw_column(path, io, k, header + (1 if readnames else 0), rows)
            v = Str(np.array(raw, dtype=object).reshape(-1, 1))
        vo = io.varopts.get(newname, {})
        v = _fill(_convert(v, io.types[k], vo), vo)
        vars_.append(v)
        names.append(newname)
    order = [names.index(s) for s in io.selected if s in names]
    T2 = Table([vars_[i] for i in order], [names[i] for i in order], None, len(rows))
    if io.missing_rule == 'omitrow':
        keep = []
        for i in range(T2.n):
            ok = True
            for v in T2.vars:
                if isinstance(v, np.ndarray) and v.dtype.kind == 'f' and np.isnan(v.reshape(T2.n, -1)[i]).any():
                    ok = False
            if ok:
                keep.append(i)
        T2 = Table([_take_rows(v, keep) for v in T2.vars], T2.names, None, len(keep))
    return T2


def _wrap(name, handler):
    info = REG.get(name)
    if info is None:
        return
    orig = info.fn

    def f(*a):
        args = a[2:] if info.ws else a[1:]
        if len(args) > 1 and isinstance(args[1], ImportOptions):
            return handler(a[1] if info.ws else a[0], *args)
        return orig(*a)
    info.fn = f


def _readtable_opts(nargout, *args):
    from .iofun import _existing
    return _read_with(_existing(args[0], 'readtable'), args[1])


def _readmatrix_opts(nargout, *args):
    from .iofun import _existing
    T = _read_with(_existing(args[0], 'readmatrix'), args[1])
    cols = [np.asarray(R._builtin('double', v), float).reshape(T.n, -1) for v in T.vars]
    return np.hstack(cols) if cols else np.zeros((T.n, 0))


def _readcell_opts(nargout, *args):
    from .iofun import _existing
    T = _read_with(_existing(args[0], 'readcell'), args[1])
    return R._builtin('table2cell', T)


_wrap('readtable', _readtable_opts)
_wrap('readmatrix', _readmatrix_opts)
_wrap('readcell', _readcell_opts)


@bi('readvars', nout=99)
def readvars(nargout, *args):
    """[Var1, ..., VarN] = readvars(filename), readvars(filename, opts), readvars(filename, Name, Value): the columns of a file, a variable each."""
    nargchk(args, 1, 20, 'readvars')
    if len(args) > 1 and isinstance(args[1], ImportOptions):
        from .iofun import _existing
        T = _read_with(_existing(args[0], 'readvars'), args[1])
    else:
        T = R._builtin('readtable', *args)
    vals = list(T.vars)
    if nargout <= 1:
        return vals[0] if vals else EMPTY()
    if nargout > len(vals):
        raise err('MATLAB:maxlhs', f'The file has {len(vals)} variables.', 'readvars')
    return tuple(vals[:nargout])


# ---- XML documents ------------------------------------------------------------------------------------------------------------------

def _str(v):
    return Char.of(v if v is not None else '')


class DomNode(Obj):
    """A node of an XML document (a document, element, attribute, text or comment), its methods called as a Java object's are."""
    is_handle = True

    def __init__(self, node):
        self.node = node

    @property
    def cls(self):
        n = self.node
        t = getattr(n, 'nodeType', 0)
        return {9: 'org.apache.xerces.dom.DeferredDocumentImpl', 1: 'org.apache.xerces.dom.DeferredElementImpl', 2: 'org.apache.xerces.dom.AttrImpl',
                3: 'org.apache.xerces.dom.DeferredTextImpl', 8: 'org.apache.xerces.dom.DeferredCommentImpl'}.get(t, 'org.w3c.dom.Node')

    def index(self, args):
        if args:
            raise MError('MATLAB:badsubscript', 'A node is called with no arguments, as node.getNodeName().')
        return self

    def doc(self):
        n = self.node
        return n if n.nodeType == 9 else n.ownerDocument

    def getprop(self, name):
        n = self.node
        m = name
        zero = {
            'getDocumentElement': lambda: _wrap_node(n.documentElement),
            'getNodeName': lambda: _str(n.nodeName),
            'getTagName': lambda: _str(getattr(n, 'tagName', n.nodeName)),
            'getLocalName': lambda: _str(n.localName or n.nodeName),
            'getNodeValue': lambda: _str(n.nodeValue) if n.nodeValue is not None else EMPTY(),
            'getNodeType': lambda: float(n.nodeType),
            'getTextContent': lambda: _str(_text(n)),
            'getData': lambda: _str(getattr(n, 'data', '')),
            'getName': lambda: _str(getattr(n, 'name', n.nodeName)),
            'getValue': lambda: _str(getattr(n, 'value', n.nodeValue)),
            'getChildNodes': lambda: NodeList(list(n.childNodes)),
            'getFirstChild': lambda: _wrap_node(n.firstChild),
            'getLastChild': lambda: _wrap_node(n.lastChild),
            'getNextSibling': lambda: _wrap_node(n.nextSibling),
            'getPreviousSibling': lambda: _wrap_node(n.previousSibling),
            'getParentNode': lambda: _wrap_node(n.parentNode),
            'getOwnerDocument': lambda: _wrap_node(self.doc()),
            'getAttributes': lambda: NamedMap(n) if n.nodeType == 1 else EMPTY(),
            'hasChildNodes': lambda: bool(n.hasChildNodes()),
            'hasAttributes': lambda: bool(n.nodeType == 1 and n.attributes.length > 0),
            'normalize': lambda: (n.normalize(), None)[1] or EMPTY(),
            'getLength': lambda: float(len(getattr(n, 'data', ''))),
        }
        if m in zero:
            return zero[m]()
        with_args = ('getElementsByTagName', 'getAttribute', 'setAttribute', 'hasAttribute', 'removeAttribute', 'appendChild', 'removeChild',
                     'insertBefore', 'replaceChild', 'createElement', 'createTextNode', 'createComment', 'setTextContent', 'setNodeValue',
                     'cloneNode', 'getAttributeNode', 'item', 'isEqualNode', 'setData')
        if m in with_args:
            return BoundMethod(self, m)
        raise MError('MATLAB:noSuchMethodOrField', f"No method '{name}' for a node of an XML document here.")

    def call(self, m, args):
        n = self.node
        s = [py_str(a) if is_str(a) else a for a in args]
        if m == 'getElementsByTagName':
            return NodeList(list(n.getElementsByTagName(s[0])))
        if m == 'getAttribute':
            return _str(n.getAttribute(s[0]))
        if m == 'getAttributeNode':
            return _wrap_node(n.getAttributeNode(s[0]))
        if m == 'setAttribute':
            n.setAttribute(s[0], s[1] if isinstance(s[1], str) else _numtext(s[1]))
            return None
        if m == 'hasAttribute':
            return bool(n.hasAttribute(s[0]))
        if m == 'removeAttribute':
            if n.hasAttribute(s[0]):
                n.removeAttribute(s[0])
            return None
        if m == 'appendChild':
            return _wrap_node(n.appendChild(_unwrap(args[0])))
        if m == 'removeChild':
            return _wrap_node(n.removeChild(_unwrap(args[0])))
        if m == 'insertBefore':
            return _wrap_node(n.insertBefore(_unwrap(args[0]), _unwrap(args[1]) if isinstance(args[1], DomNode) else None))
        if m == 'replaceChild':
            return _wrap_node(n.replaceChild(_unwrap(args[0]), _unwrap(args[1])))
        if m == 'createElement':
            return _wrap_node(self.doc().createElement(s[0]))
        if m == 'createTextNode':
            return _wrap_node(self.doc().createTextNode(s[0] if isinstance(s[0], str) else _numtext(s[0])))
        if m == 'createComment':
            return _wrap_node(self.doc().createComment(s[0]))
        if m == 'setTextContent':
            for c in list(n.childNodes):
                n.removeChild(c)
            n.appendChild(self.doc().createTextNode(s[0] if isinstance(s[0], str) else _numtext(s[0])))
            return None
        if m in ('setNodeValue', 'setData'):
            n.nodeValue = s[0] if isinstance(s[0], str) else _numtext(s[0])
            return None
        if m == 'cloneNode':
            return _wrap_node(n.cloneNode(bool(num(args[0])) if args else False))
        if m == 'isEqualNode':
            return bool(n.isSameNode(_unwrap(args[0])) or n.toxml() == _unwrap(args[0]).toxml())
        raise MError('MATLAB:noSuchMethodOrField', f"No method '{m}' for a node of an XML document here.")

    def display_lines(self):
        n = self.node
        if n.nodeType == 9:
            return ['', '[#document: null]']
        if n.nodeType == 1:
            return ['', f'[{n.nodeName}: null]']
        return ['', f'[{n.nodeName}: {n.nodeValue}]']


def _numtext(v):
    try:
        return py_str(R._builtin('num2str', v))
    except Exception:
        return str(v)


def _text(n):
    if n.nodeType in (3, 4, 8):
        return n.data
    if n.nodeType == 2:
        return n.value
    return ''.join(_text(c) for c in n.childNodes if c.nodeType in (1, 3, 4))


def _wrap_node(n):
    return DomNode(n) if n is not None else EMPTY()


def _unwrap(v):
    if not isinstance(v, DomNode):
        raise err('MATLAB:xml:node', 'A node of an XML document is needed here.', 'xml')
    return v.node


class BoundMethod(Obj):
    """A node's method waiting for its arguments: node.method(args)."""
    cls = 'java.lang.reflect.Method'
    is_handle = True

    def __init__(self, owner, name):
        self.owner, self.name = owner, name

    def index(self, args):
        r = self.owner.call(self.name, list(args))
        return EMPTY() if r is None else r


class NodeList(Obj):
    cls = 'org.apache.xerces.dom.DeepNodeListImpl'
    is_handle = True

    def __init__(self, nodes):
        self.nodes = nodes

    def index(self, args):
        if args:
            raise MError('MATLAB:badsubscript', 'Take a node from the list with item(k), counting from 0.')
        return self

    def getprop(self, name):
        if name == 'getLength':
            return float(len(self.nodes))
        if name == 'item':
            return BoundMethod(self, 'item')
        raise MError('MATLAB:noSuchMethodOrField', f"No method '{name}' for a node list here (getLength, item).")

    def call(self, m, args):
        k = int(num(args[0]))
        return _wrap_node(self.nodes[k]) if 0 <= k < len(self.nodes) else EMPTY()

    def display_lines(self):
        return ['', f'NodeList of {len(self.nodes)} nodes']


class NamedMap(Obj):
    cls = 'org.apache.xerces.dom.AttributeMap'
    is_handle = True

    def __init__(self, el):
        self.el = el

    def index(self, args):
        return self

    def getprop(self, name):
        if name == 'getLength':
            return float(self.el.attributes.length)
        if name in ('item', 'getNamedItem'):
            return BoundMethod(self, name)
        raise MError('MATLAB:noSuchMethodOrField', f"No method '{name}' for the attributes here (getLength, item, getNamedItem).")

    def call(self, m, args):
        at = self.el.attributes
        if m == 'item':
            k = int(num(args[0]))
            return _wrap_node(at.item(k)) if 0 <= k < at.length else EMPTY()
        return _wrap_node(at.getNamedItem(py_str(args[0])))


@bi('xmlread')
def xmlread(nargout, *args):
    """DOMnode = xmlread(filename): an XML file as a document whose methods (getDocumentElement, getElementsByTagName, getAttribute, ...) read it."""
    nargchk(args, 1, 2, 'xmlread')
    from xml.dom import minidom
    from xml.parsers.expat import ExpatError
    from .iofun import _existing
    p = _existing(args[0], 'xmlread')
    try:
        doc = minidom.parse(p)
    except ExpatError as e:
        raise err('MATLAB:xmlread:FileReadError', f'The file is not well-formed XML: {e}.', 'xmlread')
    return DomNode(doc)


@bi('xmlwrite')
def xmlwrite(nargout, *args):
    """xmlwrite(filename, DOMnode), str = xmlwrite(DOMnode): a document (or node) written as XML text, indented."""
    nargchk(args, 1, 2, 'xmlwrite')
    node = args[-1]
    if not isinstance(node, DomNode):
        raise err('MATLAB:xmlwrite:node', 'xmlwrite takes a node of an XML document.', 'xmlwrite')
    n = node.node
    text = n.toprettyxml(indent='   ', encoding='utf-8').decode('utf-8') if n.nodeType == 9 else n.toprettyxml(indent='   ')
    text = '\n'.join(line for line in text.split('\n') if line.strip())
    if len(args) == 2:
        from .iofun import abspath, files_changed
        p = abspath(py_str(args[0]))
        with open(p, 'w', encoding='utf-8') as f:
            f.write(text + '\n')
        files_changed(os.path.dirname(p))
        return None
    return Char.of(text)


@bi('com.mathworks.xml.XMLUtils.createDocument')
def create_document(nargout, *args):
    """docNode = com.mathworks.xml.XMLUtils.createDocument(rootName): a new XML document with its root element."""
    nargchk(args, 1, 1, 'createDocument')
    from xml.dom import minidom
    impl = minidom.getDOMImplementation()
    doc = impl.createDocument(None, py_str(args[0]), None)
    return DomNode(doc)
