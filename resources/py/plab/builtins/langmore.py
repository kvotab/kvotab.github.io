"""The language's smaller pieces: meta.class objects (?ClassName and
metaclass), subsref, subsasgn and substruct, namedargs2cell,
isStringScalar, base64, text encodings, textwrap, release checks,
calendar, array2timetable, fileattrib, recycle and gtext."""
import base64
import calendar as _cal
import datetime as _dt
import os
import re
import stat as _stat

import numpy as np

from . import bi as _register
from ._util import err, nargchk, out, num, opt_str, opt_lower, is_str, darr, arr
from ..values import MError, Char, Cell, Struct, Str, Obj, FH, numel, py_str, text_list, EMPTY, NOVAL, class_of, COLON
from ..graphics_base import HArr
from .. import runtime as R


def bi(*names, **kw):
    """Register, with Python's own errors given as the language's."""
    def deco(fn):
        def wrapped(*a):
            try:
                return fn(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, KeyError, OverflowError, ZeroDivisionError) as e:
                raise err(f'MATLAB:{names[0]}:InvalidInput', str(e) or 'The input is not valid.', names[0]) from None
        if kw.get('aw'):
            async def wrapped(*a):
                try:
                    return await fn(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, KeyError, OverflowError, ZeroDivisionError) as e:
                    raise err(f'MATLAB:{names[0]}:InvalidInput', str(e) or 'The input is not valid.', names[0]) from None
        wrapped.__name__ = fn.__name__
        wrapped.__doc__ = fn.__doc__
        return _register(*names, **kw)(wrapped)
    return deco


def _text(v, fn, what='The input'):
    s = opt_str(v)
    if s is None:
        raise err(f'MATLAB:{fn}:InvalidInput', f'{what} is text.', fn)
    return s


def _outs(nargout, *vals):
    return vals[:max(nargout, 1)] if nargout > 1 else vals[0]


# ---- meta.class and its parts --------------------------------------------------------------------------------------

BUILTIN_CLASSES = {
    'double', 'single', 'logical', 'char', 'string', 'cell', 'struct', 'function_handle',
    'int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32', 'uint64',
    'table', 'timetable', 'datetime', 'duration', 'calendarDuration', 'categorical', 'dictionary',
    'containers.Map', 'handle', 'sym', 'graph', 'digraph', 'MException', 'inputParser',
    'matlab.mixin.Copyable', 'matlab.mixin.SetGet', 'dynamicprops', 'matlab.apps.AppBase',
}
HANDLE_METHODS = ('addlistener', 'delete', 'eq', 'findobj', 'findprop', 'ge', 'gt', 'isvalid', 'le', 'listener',
                  'lt', 'ne', 'notify')


class MetaArr(HArr):
    """An array of meta objects (PropertyList, MethodList, ...): its class even when empty."""
    __slots__ = ('ecls',)

    def __init__(self, items, ecls, shape=None):
        a = np.empty(shape or (len(items), 1), object)
        for i, x in enumerate(items):
            a[i, 0] = x
        super().__init__(a)
        self.ecls = ecls

    @property
    def cls(self):
        return self.ecls

    def display_lines(self):
        return [f'  {self.a.shape[0]}×{self.a.shape[1]} {self.ecls} array']


class _Meta(Obj):
    """A meta object: read-only properties in a dict."""
    is_handle = True
    cls = 'meta.object'
    NAMES = ()

    def __init__(self, **p):
        self.p = p

    @property
    def valid(self):
        return True

    def getprop(self, name):
        if name in self.p:
            return self.p[name]
        for k in self.p:
            if k.lower() == name.lower():
                return self.p[k]
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{self.cls}'.")

    def setprop(self, name, value):
        raise MError('MATLAB:class:SetProhibited', f"You cannot set the read-only property '{name}' of {self.cls}.")

    def propnames(self):
        return list(self.p)

    def value_copy(self):
        return self

    def display_lines(self):
        from ..display import summary
        w = max((len(k) for k in self.p), default=0)
        return [f'  {self.cls} with properties:', ''] + [f'    {k.rjust(w)}: {summary(v)}' for k, v in self.p.items()]


class MetaProperty(_Meta):
    cls = 'meta.property'

    def getprop(self, name):
        if name.lower() == 'defaultvalue' and not self.p['HasDefault']:
            raise MError('MATLAB:class:NoDefaultDefined', f"The property '{self.p['Name']}' has no default value.")
        return super().getprop(name)


class MetaMethod(_Meta):
    cls = 'meta.method'


class MetaEvent(_Meta):
    cls = 'meta.event'


class MetaEnum(_Meta):
    cls = 'meta.EnumeratedValue'


class MetaClass(_Meta):
    """A class's description: its name, attributes, properties, methods,
    events, enumeration members and superclasses (the lists made when first
    read)."""
    cls = 'meta.class'

    def __init__(self, name, ci=None):
        attrs = ci.attrs if ci is not None else {}
        super().__init__(Name=Char.of(name), Description=Char.of(''), DetailedDescription=Char.of(''),
                         Hidden=bool(attrs.get('hidden', False)), Sealed=bool(attrs.get('sealed', False)),
                         Abstract=bool(attrs.get('abstract', False)), Enumeration=bool(ci is not None and ci.enum),
                         ConstructOnLoad=bool(attrs.get('constructonload', False)),
                         HandleCompatible=bool(ci.handle) if ci is not None else name in _HANDLE_BUILTINS,
                         InferiorClasses=Cell.empty((0, 1)), ContainingPackage=EMPTY(),
                         RestrictsSubclassing=False)
        self.name = name
        self.ci = ci
        self.lists = None

    def _lists(self):
        if self.lists is not None:
            return self.lists
        ci = self.ci
        props, methods, events, enums, supers = [], [], [], [], []
        if ci is not None:
            seen = set()
            for owner in _lineage(ci):
                defining = metaclass_of(owner)
                for n, p in owner.props.items():
                    if n in seen:
                        continue
                    seen.add(n)
                    a = p['attrs']
                    acc = a.get('access', 'public')
                    props.append(MetaProperty(
                        Name=Char.of(n), Description=Char.of(''), DetailedDescription=Char.of(''),
                        GetAccess=Char.of(str(a.get('getaccess', acc))), SetAccess=Char.of(str(a.get('setaccess', acc))),
                        Dependent=bool(a.get('dependent', False)), Constant=bool(a.get('constant', False)),
                        Abstract=bool(a.get('abstract', False)), Transient=bool(a.get('transient', False)),
                        Hidden=bool(a.get('hidden', False)), GetObservable=bool(a.get('getobservable', False)),
                        SetObservable=bool(a.get('setobservable', False)), AbortSet=bool(a.get('abortset', False)),
                        NonCopyable=bool(a.get('noncopyable', False)), HasDefault=bool(p.get('has_default')),
                        DefaultValue=p['default'], DefiningClass=defining))
            seen = set()
            if True:                         # the constructor, as the class's static method
                methods.append(MetaMethod(Name=Char.of(ci.name.split('.')[-1]), Description=Char.of(''), DetailedDescription=Char.of(''),
                                          Access=Char.of('public'), Static=True, Abstract=False, Sealed=False, Hidden=False,
                                          InputNames=Cell.empty((0, 1)), OutputNames=Cell.of_list([Char.of('obj')], (1, 1)),
                                          DefiningClass=self))
                seen.add(ci.name.split('.')[-1])
            for owner in _lineage(ci):
                defining = metaclass_of(owner)
                for n, m in owner.methods.items():
                    if n in seen:
                        continue
                    seen.add(n)
                    a = m.get('attrs') or {}
                    ins = list(m.get('params') or [])
                    methods.append(MetaMethod(
                        Name=Char.of(n), Description=Char.of(''), DetailedDescription=Char.of(''),
                        Access=Char.of(str(a.get('access', 'public'))), Static=bool(m.get('static')),
                        Abstract=bool(a.get('abstract', False)), Sealed=bool(a.get('sealed', False)),
                        Hidden=bool(a.get('hidden', False)),
                        InputNames=Cell.of_list([Char.of(x) for x in ins], (len(ins), 1)) if ins else Cell.empty((0, 1)),
                        OutputNames=Cell.empty((0, 1)), DefiningClass=defining))
            if ci.handle:
                hmc = metaclass_named('handle')
                for n in HANDLE_METHODS:
                    if n not in seen:
                        methods.append(MetaMethod(Name=Char.of(n), Description=Char.of(''), DetailedDescription=Char.of(''),
                                                  Access=Char.of('public'), Static=False, Abstract=False, Sealed=True, Hidden=False,
                                                  InputNames=Cell.empty((0, 1)), OutputNames=Cell.empty((0, 1)), DefiningClass=hmc))
            for owner in _lineage(ci):
                defining = metaclass_of(owner)
                for n in owner.events:
                    events.append(MetaEvent(Name=Char.of(n), Description=Char.of(''), DetailedDescription=Char.of(''),
                                            ListenAccess=Char.of('public'), NotifyAccess=Char.of('public'), Hidden=False,
                                            DefiningClass=defining))
            for n, _ in ci.enum:
                enums.append(MetaEnum(Name=Char.of(n), Description=Char.of(''), DetailedDescription=Char.of(''), Hidden=False,
                                      DefiningClass=self))
            supers = [metaclass_of(s) for s in ci.supers] + [metaclass_named(b) for b in ci.base_names if b not in (s.name for s in ci.supers)]
            if ci.handle and not any(b.name == 'handle' for b in supers) and not ci.supers and not ci.base_names:
                supers.append(metaclass_named('handle'))
        self.lists = {'PropertyList': MetaArr(props, 'meta.property'), 'MethodList': MetaArr(methods, 'meta.method'),
                      'EventList': MetaArr(events, 'meta.event'), 'EnumerationMemberList': MetaArr(enums, 'meta.EnumeratedValue'),
                      'SuperclassList': MetaArr([s for s in supers if s is not None], 'meta.class')}
        return self.lists

    def getprop(self, name):
        for k in ('PropertyList', 'MethodList', 'EventList', 'EnumerationMemberList', 'SuperclassList'):
            if k.lower() == name.lower():
                return self._lists()[k]
        return super().getprop(name)

    def propnames(self):
        return list(self.p) + ['PropertyList', 'MethodList', 'EventList', 'EnumerationMemberList', 'SuperclassList']

    def display_lines(self):
        from ..display import summary
        rows = [(k, summary(v)) for k, v in self.p.items()] + [(k, f'[{v.a.shape[0]}×1 {v.ecls}]') for k, v in self._lists().items()]
        w = max(len(k) for k, _ in rows)
        return [f'  {self.cls} with properties:', ''] + [f'    {k.rjust(w)}: {t}' for k, t in rows]

    def is_subclass_of(self, other):
        """Whether this class is other or derives from it."""
        if self.name == other.name:
            return True
        return other.name in (self.ci.all_names() if self.ci is not None else [self.name])


_HANDLE_BUILTINS = {'handle', 'matlab.mixin.Copyable', 'matlab.mixin.SetGet', 'dynamicprops', 'matlab.apps.AppBase', 'inputParser',
                    'containers.Map'}
_CACHE = {}


def _lineage(ci):
    """The class and its superclasses of the language's own, nearest first."""
    out_, todo = [], [ci]
    while todo:
        c = todo.pop(0)
        if c not in out_:
            out_.append(c)
            todo.extend(c.supers)
    return out_


def metaclass_of(ci):
    key = ci.name
    hit = _CACHE.get(key)
    if hit is not None and hit.ci is ci:
        return hit
    mc = MetaClass(ci.name, ci)
    _CACHE[key] = mc
    return mc


def metaclass_named(name):
    """The meta.class of a class by name, or None."""
    from .. import classdef as CD
    ci = None
    if name not in BUILTIN_CLASSES:
        try:
            ci = CD.load_class(name, R)
        except MError:
            raise
        except Exception:
            ci = None
        if ci is None:
            ci = CD.CLASSES.get(name)
    if ci is not None:
        return metaclass_of(ci)
    if name in BUILTIN_CLASSES:
        hit = _CACHE.get(name)
        if hit is None:
            hit = _CACHE[name] = MetaClass(name)
        return hit
    return None


@bi('meta.class.fromName', arr=False)
def meta_from_name(nargout, *args):
    """meta.class.fromName(name), and ?name: the class's meta.class (empty when there is no such class)."""
    nargchk(args, 1, 1, 'meta.class.fromName')
    mc = metaclass_named(_text(args[0], 'meta.class.fromName', 'The class name'))
    return mc if mc is not None else MetaArr([], 'meta.class', (0, 0))


@bi('metaclass', arr=False)
def metaclass(nargout, *args):
    """metaclass(obj): the meta.class of the object's class."""
    nargchk(args, 1, 1, 'metaclass')
    v = args[0]
    ci = getattr(v, 'ci', None)
    if ci is not None and hasattr(ci, 'props'):
        return metaclass_of(ci)
    name = class_of(v)
    mc = metaclass_named(name)
    if mc is None:
        mc = _CACHE.get(name)
        if mc is None:
            mc = _CACHE[name] = MetaClass(name)
    return mc


_OPNAMES = {'eq': '==', 'ne': '~=', 'lt': '<', 'le': '<=', 'gt': '>', 'ge': '>='}


def _meta_compare(op, *xs):
    """meta.class == < <= > >= ~=: the same class, or a subclass of the other."""
    op = _OPNAMES.get(op, op)
    if len(xs) != 2 or not all(isinstance(x, MetaClass) for x in xs):
        raise err('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for operands of these types.", 'meta.class')
    a, b = xs
    if not (isinstance(a, MetaClass) and isinstance(b, MetaClass)):
        raise err('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for operands of these types.", 'meta.class')
    if op == '==':
        return a.name == b.name
    if op == '~=':
        return a.name != b.name
    if op == '<':
        return a.name != b.name and a.is_subclass_of(b)
    if op == '<=':
        return a.is_subclass_of(b)
    if op == '>':
        return a.name != b.name and b.is_subclass_of(a)
    if op == '>=':
        return b.is_subclass_of(a)
    raise err('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for meta.class objects.", 'meta.class')


def _install_ops():
    from .. import ops
    table = getattr(ops, 'OBJ_OPS', None)
    if table is not None:
        table[MetaClass] = _meta_compare


_install_ops()


# ---- subsref, subsasgn, substruct ---------------------------------------------------------------------------------

def _steps(S, fn):
    """The (type, subs) steps of a subscript struct, subs as the indexing
    functions take them."""
    if not isinstance(S, Struct) or 'type' not in S.f or 'subs' not in S.f:
        raise err(f'MATLAB:{fn}:InvalidSubscript', 'The subscripts are a struct array with the fields type and subs (substruct makes one).', fn)
    steps = []
    for i in range(S.size):
        e = S.elem(i)
        t = py_str(e['type'])
        s = e['subs']
        if t in ('()', '{}'):
            if not isinstance(s, Cell):
                raise err(f'MATLAB:{fn}:InvalidSubscript', f"The subs of a '{t}' step is a cell array of indices.", fn)
            idx = []
            for x in s.a.reshape(-1, order='F'):
                if isinstance(x, (Char, Str)) and py_str(x) == ':':
                    idx.append(COLON)
                elif isinstance(x, np.ndarray) and x.size == 1 and x.dtype.kind == 'f':
                    idx.append(float(x.reshape(-1)[0]))
                else:
                    idx.append(x)
            steps.append((t, tuple(idx)))
        elif t == '.':
            name = opt_str(s)
            if name is None:
                raise err(f'MATLAB:{fn}:InvalidSubscript', "The subs of a '.' step is a field or property name.", fn)
            steps.append(('.', name))
        else:
            raise err(f'MATLAB:{fn}:InvalidSubscript', f"A subscript's type is '()', '{{}}' or '.', not '{t}'.", fn)
    if not steps:
        raise err(f'MATLAB:{fn}:InvalidSubscript', 'The subscripts are empty.', fn)
    return steps


@bi('substruct', arr=False)
def substruct(nargout, *args):
    """S = substruct(type1, subs1, type2, subs2, ...): the subscripts for subsref and subsasgn."""
    if not args or len(args) % 2:
        raise err('MATLAB:substruct:nargin', 'substruct takes pairs of a type and its subscripts.', 'substruct')
    n = len(args) // 2
    S = Struct.empty((1, n), ('type', 'subs'))
    for k in range(n):
        t, s = args[2 * k], args[2 * k + 1]
        ts = opt_str(t)
        if ts not in ('()', '{}', '.'):
            raise err('MATLAB:substruct:BadType', "Each type is '()', '{}' or '.'.", 'substruct')
        if ts == '.' and opt_str(s) is None:
            raise err('MATLAB:substruct:BadSubs', "The subscript of '.' is a field name.", 'substruct')
        if ts != '.' and not isinstance(s, Cell):
            raise err('MATLAB:substruct:BadSubs', f"The subscripts of '{ts}' are a cell array.", 'substruct')
        S.f['type'][0, k] = Char.of(ts)
        S.f['subs'][0, k] = s
    return S


@bi('subsref', nout=99, arr=False)
def subsref(nargout, *args):
    """B = subsref(A, S): A indexed by the steps in S, as A(...), A{...} and A.name would."""
    from .. import index as I
    nargchk(args, 2, 2, 'subsref')
    vals = [args[0]]
    for t, s in _steps(args[1], 'subsref'):
        v = I.one(vals, 'curly brace')
        if t == '()':
            vals = [I.idx(v, s)]
        elif t == '{}':
            vals = I.cidx(v, s)
        else:
            vals = I.fld(v, s)
    if nargout <= 1:
        return I.one(vals, 'curly brace') if len(vals) != 1 else vals[0]
    if len(vals) < nargout:
        raise err('MATLAB:needMoreRhsOutputs', 'Insufficient number of outputs from right hand side of equal sign to satisfy assignment.', 'subsref')
    return tuple(vals[:nargout])


@bi('subsasgn', arr=False)
def subsasgn(nargout, *args):
    """A = subsasgn(A, S, B): A with B assigned through the steps in S, as A(...) = B would."""
    from .. import index as I
    nargchk(args, 3, 3, 'subsasgn')
    from ..values import share
    A = args[0]
    try:
        A = A.value_copy() if hasattr(A, 'value_copy') and not getattr(A, 'is_handle', False) else A
    except Exception:
        pass
    return I.asgn_chain(share(A) if A is not NOVAL else A, tuple(_steps(args[1], 'subsasgn')), args[2])


# ---- small conversions -------------------------------------------------------------------------------------------

@bi('namedargs2cell', arr=False)
def namedargs2cell(nargout, *args):
    """C = namedargs2cell(s): a scalar struct's fields as {name1, value1, name2, value2, ...}."""
    nargchk(args, 1, 1, 'namedargs2cell')
    s = args[0]
    if not isinstance(s, Struct) or s.size != 1:
        raise err('MATLAB:namedargs2cell:InvalidInput', 'The input is a scalar struct.', 'namedargs2cell')
    items = []
    for k in s.keys:
        items += [Char.of(k), s.get1(k)]
    return Cell.of_list(items, (1, len(items))) if items else Cell.empty((1, 0))


@bi('isStringScalar', arr=False)
def isStringScalar(nargout, *args):
    """tf = isStringScalar(s): whether s is a string array with one element."""
    nargchk(args, 1, 1, 'isStringScalar')
    return isinstance(args[0], Str) and numel(args[0]) == 1


def _bytes_of(v, fn):
    if isinstance(v, (Char, Str)):
        return py_str(v).encode('utf-8')
    a = np.asarray(arr(v, fn))
    if a.size and (a.dtype.kind not in 'uif' or np.any(a != np.round(a)) or a.min() < 0 or a.max() > 255):
        raise err(f'MATLAB:{fn}:InvalidInput', 'The input is text or a vector of bytes (whole numbers from 0 to 255).', fn)
    return bytes(a.reshape(-1, order='F').astype(np.uint8).tolist())


@bi('matlab.net.base64encode', arr=False)
def base64encode(nargout, *args):
    """b64 = matlab.net.base64encode(V): bytes (uint8, or text as UTF-8) as Base64 text; a string for a string."""
    nargchk(args, 1, 1, 'matlab.net.base64encode')
    s = base64.b64encode(_bytes_of(args[0], 'base64encode')).decode('ascii')
    return Str.of(s) if isinstance(args[0], Str) else Char.of(s)


@bi('matlab.net.base64decode', arr=False)
def base64decode(nargout, *args):
    """V = matlab.net.base64decode(b64): Base64 text back to its bytes, a uint8 row."""
    nargchk(args, 1, 1, 'matlab.net.base64decode')
    t = _text(args[0], 'base64decode', 'Base64')
    t = re.sub(r'\s+', '', t)
    try:
        b = base64.b64decode(t + '=' * (-len(t) % 4), validate=True)
    except Exception:
        raise err('MATLAB:base64decode:InvalidInput', 'The text is not Base64.', 'matlab.net.base64decode') from None
    return np.frombuffer(b, np.uint8).reshape(1, -1).copy()


_ENC_ALIASES = {'': 'utf-8', 'system': 'utf-8', 'utf8': 'utf-8', 'latin1': 'latin-1', 'iso-8859-1': 'latin-1', 'windows-1252': 'cp1252',
                'us-ascii': 'ascii', 'shift_jis': 'shift_jis', 'utf-16': 'utf-16'}


def _encoding(v, fn):
    e = 'utf-8' if v is None else _text(v, fn, 'The encoding').strip()
    e = _ENC_ALIASES.get(e.lower(), e)
    import codecs
    try:
        return codecs.lookup(e).name
    except LookupError:
        raise err(f'MATLAB:{fn}:UnknownEncoding', f"'{e}' is not an encoding known here.", fn) from None


@bi('unicode2native', arr=False)
def unicode2native(nargout, *args):
    """bytes = unicode2native(str, encoding): text as the bytes of an encoding (UTF-8 by default), a uint8 row."""
    nargchk(args, 1, 2, 'unicode2native')
    s = _text(args[0], 'unicode2native', 'The input')
    enc = _encoding(args[1] if len(args) > 1 else None, 'unicode2native')
    b = s.encode(enc, errors='replace')
    if enc in ('utf-16', 'utf-32'):
        b = b[2:] if enc == 'utf-16' else b[4:]      # no byte-order mark
    return np.frombuffer(b, np.uint8).reshape(1, -1).copy()


@bi('native2unicode', arr=False)
def native2unicode(nargout, *args):
    """str = native2unicode(bytes, encoding): bytes of an encoding (UTF-8 by default) as text."""
    nargchk(args, 1, 2, 'native2unicode')
    b = _bytes_of(args[0], 'native2unicode') if not isinstance(args[0], (Char, Str)) else bytes(ord(c) & 0xFF for c in py_str(args[0]))
    enc = _encoding(args[1] if len(args) > 1 else None, 'native2unicode')
    return Char.of(b.decode(enc, errors='replace'))


@bi('textwrap', nout=2, arr=False)
def textwrap(nargout, *args):
    """outstring = textwrap(instring, columns): each paragraph (cell element or
    string) wrapped at word boundaries into lines of at most columns
    characters, as a column cell array; textwrap(h, instring) fits the width
    of a uicontrol (its width in characters, about 7 pixels each)."""
    nargchk(args, 2, 3, 'textwrap')
    a = list(args)
    pos = None
    if not isinstance(a[0], (Cell, Char, Str)):
        h = a[0]
        try:
            p = np.asarray(darr(h.getprop('Position')), float).reshape(-1)
            width = max(int(p[2] // 7) - 1, 1)
            pos = p
        except Exception:
            raise err('MATLAB:textwrap:InvalidHandle', 'The first input is a uicontrol, or the text.', 'textwrap') from None
        text = a[1]
    else:
        text = a[0]
        width = int(num(a[1]))
        if width < 1:
            raise err('MATLAB:textwrap:BadColumns', 'columns is a positive whole number.', 'textwrap')
    paras = text_list(text) if isinstance(text, (Cell, Str)) else py_str(text).split('\n') if '\n' in py_str(text) else [py_str(text)]
    lines = []
    for para in paras:
        words = para.split()
        if not words:
            lines.append('')
            continue
        cur = ''
        for w in words:
            while len(w) > width:
                if cur:
                    lines.append(cur)
                    cur = ''
                lines.append(w[:width])
                w = w[width:]
            if not cur:
                cur = w
            elif len(cur) + 1 + len(w) <= width:
                cur += ' ' + w
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
    C = Cell.of_list([Char.of(x) for x in lines], (len(lines), 1)) if lines else Cell.empty((0, 1))
    if nargout > 1:
        if pos is None:
            raise err('MATLAB:textwrap:NoPosition', 'The position comes with the uicontrol form, textwrap(h, instring).', 'textwrap')
        npos = pos.copy()
        npos[3] = max(npos[3], 16 * len(lines) + 4)
        return C, npos.reshape(1, -1)
    return C


# ---- the release -------------------------------------------------------------------------------------------------

_RELEASE = re.compile(r'^R(\d{4})([ab])$', re.I)


@bi('isMATLABReleaseOlderThan', arr=False)
def isMATLABReleaseOlderThan(nargout, *args):
    """tf = isMATLABReleaseOlderThan(release, stage, update): false here:
    PyLAB follows the language as it is now, so no release is newer than it."""
    nargchk(args, 1, 3, 'isMATLABReleaseOlderThan')
    r = _text(args[0], 'isMATLABReleaseOlderThan', 'The release').strip()
    if not _RELEASE.match(r):
        raise err('MATLAB:isMATLABReleaseOlderThan:InvalidRelease', "The release is like 'R2024b'.", 'isMATLABReleaseOlderThan')
    if len(args) > 1 and (opt_lower(args[1]) or '') not in ('release', 'prerelease'):
        raise err('MATLAB:isMATLABReleaseOlderThan:InvalidStage', "The stage is 'release' or 'prerelease'.", 'isMATLABReleaseOlderThan')
    if len(args) > 2:
        u = float(num(args[2]))
        if u < 0 or u != int(u):
            raise err('MATLAB:isMATLABReleaseOlderThan:InvalidUpdate', 'The update is a whole number from 0.', 'isMATLABReleaseOlderThan')
    return False


@bi('verLessThan', arr=False)
def verLessThan(nargout, *args):
    """tf = verLessThan(toolbox, version): false here: PyLAB counts as no
    older than any version of the language or of its toolboxes."""
    nargchk(args, 2, 2, 'verLessThan')
    _text(args[0], 'verLessThan', 'The toolbox name')
    v = _text(args[1], 'verLessThan', 'The version')
    if not re.match(r'^\d+(\.\d+)*$', v.strip()):
        raise err('MATLAB:verLessThan:badVersion', "The version is numbers separated by periods, like '9.14'.", 'verLessThan')
    return False


# ---- dates and files ---------------------------------------------------------------------------------------------

@bi('calendar', arr=False)
def calendar(nargout, *args):
    """c = calendar, calendar(d), calendar(y, m): a month's days as a 6-by-7
    matrix, weeks from Sunday, zeros outside the month; with no output the
    month is printed."""
    nargchk(args, 0, 2, 'calendar')
    if not args:
        t = _dt.date.today()
        y, m = t.year, t.month
    elif len(args) == 1:
        v = args[0]
        if class_of(v) == 'datetime':
            from .timetypes import DateTime
            parts = R.BUILTINS['datevec'].fn(1, v)
            vv = np.asarray(darr(parts)).reshape(-1)
            y, m = int(vv[0]), int(vv[1])
        elif isinstance(v, (Char, Str)):
            vv = np.asarray(darr(R.BUILTINS['datevec'].fn(1, v))).reshape(-1)
            y, m = int(vv[0]), int(vv[1])
        else:
            d = _dt.date.fromordinal(int(num(v)) - 366) if float(num(v)) > 366 else None
            if d is None:
                raise err('MATLAB:calendar:InvalidDate', 'The date is a datenum, a datetime or date text.', 'calendar')
            y, m = d.year, d.month
    else:
        y, m = int(num(args[0])), int(num(args[1]))
        if not 1 <= m <= 12:
            raise err('MATLAB:calendar:InvalidMonth', 'The month is from 1 to 12.', 'calendar')
    first, ndays = _cal.monthrange(y, m) if y >= 1 else (0, 0)
    if y < 1:
        raise err('MATLAB:calendar:InvalidYear', 'The year is from 1.', 'calendar')
    first = (first + 1) % 7                          # Monday 0 -> Sunday 0
    c = np.zeros((6, 7))
    for d in range(1, ndays + 1):
        k = first + d - 1
        c[k // 7, k % 7] = d
    if nargout:
        return c
    R.write(f'{_cal.month_abbr[m]:>17} {y}\n')
    R.write('     S     M    Tu     W    Th     F     S\n')
    for row in c:
        R.write(''.join(f'{int(x):6d}' if x else '     0' for x in row) + '\n')
    return None


@bi('array2timetable', arr=False)
def array2timetable(nargout, *args):
    """TT = array2timetable(X, 'RowTimes', t) (or 'SampleRate', 'TimeStep',
    'StartTime'; 'VariableNames', 'DimensionNames'): a timetable with each
    column of X as a variable, named Var1, Var2, ... unless named."""
    nargchk(args, 3, None, 'array2timetable')
    X = args[0]
    if isinstance(X, (Cell, Struct)) or getattr(X, 'cls', '') in ('table', 'timetable'):
        raise err('MATLAB:array2timetable:InvalidInput', 'X is a matrix (cell2table and table2timetable take the others).', 'array2timetable')
    rest = list(args[1:])
    if len(rest) % 2:
        raise err('MATLAB:array2timetable:nargin', 'The options come as names and values.', 'array2timetable')
    names = None
    keep = []
    for i in range(0, len(rest), 2):
        k = opt_lower(rest[i])
        if k is None:
            raise err('MATLAB:array2timetable:BadOption', 'Each option is named by text.', 'array2timetable')
        if k == 'variablenames':
            names = [str(x) for x in text_list(rest[i + 1])]
        else:
            keep += [rest[i], rest[i + 1]]
    if not any(opt_lower(keep[i]) in ('rowtimes', 'samplerate', 'timestep') for i in range(0, len(keep), 2)):
        raise err('MATLAB:array2timetable:NoRowTimes', "Give 'RowTimes', 'SampleRate' or 'TimeStep'.", 'array2timetable')
    a = X
    sh = getattr(a, 'shape', None) or np.shape(a)
    if len(sh) != 2:
        raise err('MATLAB:array2timetable:NotMatrix', 'X is a matrix.', 'array2timetable')
    from .. import index as I
    cols = [I.idx(a, (COLON, float(j + 1))) for j in range(sh[1])]
    names = names or [f'Var{j + 1}' for j in range(sh[1])]
    if len(names) != sh[1]:
        raise err('MATLAB:array2timetable:VariableNames', f'Give {sh[1]} variable names, one for each column.', 'array2timetable')
    vn = Cell.of_list([Char.of(n) for n in names], (1, len(names))) if names else Cell.empty((1, 0))
    return R.BUILTINS['timetable'].fn(1, *cols, *keep, Char.of('VariableNames'), vn)


_ATTRS = ('Name', 'archive', 'system', 'hidden', 'directory', 'UserRead', 'UserWrite', 'UserExecute',
          'GroupRead', 'GroupWrite', 'GroupExecute', 'OtherRead', 'OtherWrite', 'OtherExecute')


def _attr_struct(paths):
    S = Struct.empty((len(paths), 1) if len(paths) != 1 else (1, 1), _ATTRS)
    for i, p in enumerate(paths):
        st = os.stat(p)
        m = st.st_mode
        vals = {'Name': Char.of(p), 'archive': np.nan, 'system': np.nan, 'hidden': np.nan,
                'directory': bool(_stat.S_ISDIR(m)),
                'UserRead': bool(m & _stat.S_IRUSR), 'UserWrite': bool(m & _stat.S_IWUSR), 'UserExecute': bool(m & _stat.S_IXUSR),
                'GroupRead': bool(m & _stat.S_IRGRP), 'GroupWrite': bool(m & _stat.S_IWGRP), 'GroupExecute': bool(m & _stat.S_IXGRP),
                'OtherRead': bool(m & _stat.S_IROTH), 'OtherWrite': bool(m & _stat.S_IWOTH), 'OtherExecute': bool(m & _stat.S_IXOTH)}
        for k in _ATTRS:
            S.f[k].reshape(-1, order='F')[i] = vals[k]
    return S


@bi('fileattrib', nout=3, arr=False)
def fileattrib(nargout, *args):
    """[status, values, msgid] = fileattrib(name): a file's or folder's
    attributes (a struct of Name, directory and the read, write and execute
    permissions; archive, system and hidden are NaN here); a * matches
    several. fileattrib(name, mode, users) changes them: mode like '+w' or
    '-x', users 'u', 'g', 'o' or 'a'."""
    nargchk(args, 0, 4, 'fileattrib')
    from .iofun import abspath
    import glob
    name = _text(args[0], 'fileattrib', 'The name') if args else '.'
    p = abspath(name)
    paths = sorted(glob.glob(p)) if any(c in name for c in '*?') else ([p] if os.path.exists(p) else [])
    if not paths:
        if nargout <= 1 and len(args) < 2:
            if nargout == 0:
                raise err('MATLAB:FILEATTRIB:CannotFindFile', 'No such file or directory.', 'fileattrib')
            return False
        return _outs(nargout, False, Char.of('No such file or directory.'), Char.of('MATLAB:FILEATTRIB:CannotFindFile'))
    if len(args) >= 2:
        mode = _text(args[1], 'fileattrib', 'The mode').replace(' ', '')
        users = (_text(args[2], 'fileattrib', 'The users') if len(args) > 2 and numel(args[2]) else 'u').lower()
        bits = {'r': 'R', 'w': 'W', 'x': 'X'}
        who = {'u': 'USR', 'g': 'GRP', 'o': 'OTH'}
        changes = re.findall(r'([+-])([rwxahs]+)', mode)
        if not changes:
            raise err('MATLAB:FILEATTRIB:BadMode', "The mode is like '+w' or '-x'.", 'fileattrib')
        targets = paths
        if len(args) > 3 and (opt_lower(args[3]) or '') == 's':
            targets = []
            for q in paths:
                targets.append(q)
                if os.path.isdir(q):
                    for root, dirs, files in os.walk(q):
                        targets += [os.path.join(root, f) for f in dirs + files]
        for q in targets:
            m = os.stat(q).st_mode
            for sign, letters in changes:
                for L in letters:
                    if L not in bits:
                        continue                 # archive, hidden, system: Windows only
                    for u in ('ugo' if 'a' in users else users):
                        if u not in who:
                            continue
                        flag = getattr(_stat, f'S_I{bits[L]}{who[u]}')
                        m = (m | flag) if sign == '+' else (m & ~flag)
            os.chmod(q, _stat.S_IMODE(m))
        return _outs(nargout, True, Char.of(''), Char.of(''))
    S = _attr_struct(paths)
    if nargout == 0:
        from ..display import display, struct_field_lines
        R.write('\n'.join(struct_field_lines(S)) + '\n' if S.size == 1 else display('ans', S))
        return None
    return _outs(nargout, True, S, Char.of(''))


_RECYCLE = ['off']


@bi('recycle', arr=False)
def recycle(nargout, *args):
    """recycle('on') or recycle('off'), and the state it was in: kept only;
    delete removes files for good here (there is no recycle bin)."""
    nargchk(args, 0, 1, 'recycle')
    old = _RECYCLE[0]
    if args:
        s = opt_lower(args[0])
        if s not in ('on', 'off'):
            raise err('MATLAB:recycle:BadState', "recycle takes 'on' or 'off'.", 'recycle')
        _RECYCLE[0] = s
        return Char.of(old) if nargout else None
    return Char.of(old)


@bi('gtext', aw=True, arr=False)
async def gtext(nargout, *args):
    """gtext(str) and gtext(str, Name, Value): text placed where the next
    click in the current figure lands; a cell array or several rows place one
    line at each click."""
    nargchk(args, 1, None, 'gtext')
    v = args[0]
    items = text_list(v) if isinstance(v, (Cell, Str)) else [py_str(v)] if isinstance(v, Char) and v.shape[0] <= 1 else \
        [py_str(Char(v.a[i:i + 1, :])) for i in range(v.shape[0])] if isinstance(v, Char) else None
    if items is None:
        raise err('MATLAB:gtext:InvalidInput', 'The text is a character vector, a string or a cell array of them.', 'gtext')
    hs = []
    for s in items:
        pt = await R.BUILTINS['ginput'].fn(1, 1.0)
        a = np.asarray(darr(pt)).reshape(-1)
        if a.size < 2:
            break
        h = R.BUILTINS['text'].fn(1, float(a[0]), float(a[1]), Char.of(s), *args[1:])
        hs.append(h)
    if not nargout:
        return None
    return hs[0] if len(hs) == 1 else HArr.of(hs, col=True)
