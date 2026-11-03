"""Classes of the language's own: classdef files.

A classdef file is cut into its sections with the lexer's tokens: the
header (name, superclasses), properties (names, class and size given or
not, defaults), methods (each function's text), events. The methods are
compiled together as the functions of one module, each renamed M__name so
that a method named as a builtin (delete, disp, plus) never hides it from
the class's own code; the constructor takes the new object as a first
argument and starts with it as its output. Super calls (obj@Super(...),
method@Super(obj, ...)) become calls of plabSuperCall.

An object (UObj) holds its class and its property values. A handle class
(a subclass of handle, or of matlab.apps.AppBase and kin) is shared; a
value class is copied when one of its copies changes. Methods are found by
name: obj.method(...), method(obj, ...) (runtime.call asks here first) and
the operators and builtins that a class defines (dispatchers put in front
of them, the builtins then awaited by the compiled code).
"""
import re

import numpy as np

from .values import MError, Obj, Char, Cell, Struct, FH, NOVAL, EMPTY, share
from .lexer import tokenize

HANDLE_BASES = {'handle', 'matlab.apps.AppBase', 'dynamicprops', 'matlab.mixin.Copyable', 'matlab.mixin.SetGet',
                'matlab.mixin.SetGetExactNames', 'hgsetget', 'matlab.mixin.Heterogeneous', 'matlab.mixin.CustomDisplay'}
CLASSES = {}         # name -> ClassInfo (the loaded ones)
_OVERRIDDEN = set()  # builtins a class's method has a dispatcher in front of


class ClassInfo:
    def __init__(self, name, path):
        self.name = name
        self.path = path
        self.supers = []             # ClassInfo of the language's own superclasses
        self.base_names = []         # every superclass name, the built-in ones too
        self.handle = False
        self.props = {}              # name -> dict(default=..., attrs=..., cls=...)
        self.methods = {}            # name -> dict(fn=async fn, static=bool, attrs=...)
        self.getters = {}
        self.setters = {}
        self.events = []
        self.ctor = None
        self.attrs = {}

    def all_names(self):
        out = [self.name]
        for s in self.supers:
            for n in s.all_names():
                if n not in out:
                    out.append(n)
        for n in self.base_names:
            if n not in out:
                out.append(n)
        if self.handle and 'handle' not in out:
            out.append('handle')
        return out

    def find_method(self, name):
        m = self.methods.get(name)
        if m is not None:
            return m
        for s in self.supers:
            m = s.find_method(name)
            if m is not None:
                return m
        return None

    def find_prop(self, name):
        p = self.props.get(name)
        if p is not None:
            return p
        for s in self.supers:
            p = s.find_prop(name)
            if p is not None:
                return p
        return None

    def prop_names(self, public_only=True):
        names = []
        for s in self.supers:
            for n in s.prop_names(public_only):
                if n not in names:
                    names.append(n)
        for n, p in self.props.items():
            acc = (p['attrs'].get('access') or p['attrs'].get('getaccess') or 'public').lower()
            if public_only and acc in ('private', 'protected'):
                continue
            if p['attrs'].get('hidden') or p['attrs'].get('constant') and public_only and False:
                continue
            if n not in names:
                names.append(n)
        return names

    def getter(self, name):
        if name in self.getters:
            return self.getters[name]
        for s in self.supers:
            g = s.getter(name)
            if g is not None:
                return g
        return None

    def setter(self, name):
        if name in self.setters:
            return self.setters[name]
        for s in self.supers:
            g = s.setter(name)
            if g is not None:
                return g
        return None


class BoundMethod(FH):
    """obj.method: the method with the object as its first argument."""
    __slots__ = ('obj', 'mname', 'fn')

    def __init__(self, obj, mname, fn):
        self.obj = obj
        self.mname = mname
        self.fn = fn

    def text(self):
        return f'@(varargin) {self.mname}(obj, varargin{{:}})'

    def name(self):
        return self.mname

    async def acall(self, nargout, *args):
        # obj.method(...) as a statement asks for one output; a method with none gives none
        nouts = getattr(self.fn, 'nouts', 99)
        return await self.fn(min(nargout, nouts), self.obj, *args)

    def scall(self, nargout, *args):
        from .runtime import run_sync
        return run_sync(self.acall(nargout, *args))


class UObj(Obj):
    """An object of a class of the language's own."""
    __slots__ = ('ci', 'p', 'alive', 'listeners', 'uid', 'deleting')
    _n = [0]

    def __init__(self, ci):
        self.ci = ci
        self.p = {}
        self.alive = True
        self.deleting = False
        self.listeners = {}
        UObj._n[0] += 1
        self.uid = UObj._n[0]

    @property
    def is_handle(self):
        return self.ci.handle

    @property
    def cls(self):
        return self.ci.name

    @property
    def superclasses(self):
        return self.ci.all_names()[1:]

    @property
    def valid(self):
        return self.alive

    def value_copy(self):
        if self.ci.handle:
            return self
        o = UObj(self.ci)
        o.p = {k: share(v) for k, v in self.p.items()}
        return o

    def _check(self):
        if not self.alive:
            raise MError('MATLAB:class:InvalidHandle', 'Invalid or deleted object.')

    def getprop(self, name):
        self._check()
        ci = self.ci
        p = ci.find_prop(name)
        if p is not None:
            if p['attrs'].get('dependent'):
                g = ci.getter(name)
                if g is None:
                    raise MError('MATLAB:class:GetProhibited', f"The Dependent property '{name}' of class '{ci.name}' has no get method.")
                from .runtime import run_sync
                return run_sync(g(1, self))
            if p['attrs'].get('constant'):
                return p['default']
            return self.p.get(name, EMPTY())
        m = ci.find_method(name)
        if m is not None:
            if m['static']:
                return BoundStatic(name, m['fn'])
            return BoundMethod(self, name, m['fn'])
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{ci.name}'.")

    def setprop(self, name, value):
        self._check()
        ci = self.ci
        p = ci.find_prop(name)
        if p is None:
            raise MError('MATLAB:noPublicFieldForClass', f"Unrecognized property '{name}' for class '{ci.name}'.")
        if p['attrs'].get('constant'):
            raise MError('MATLAB:class:SetProhibited', f"Unable to set the '{name}' property of class '{ci.name}' because it is a Constant property.")
        s = ci.setter(name)
        if s is not None and not _IN_SETTER.get((id(self), name)):
            from .runtime import run_sync
            _IN_SETTER[(id(self), name)] = True
            try:
                r = run_sync(s(1 if not ci.handle else 0, self, value))
            finally:
                _IN_SETTER.pop((id(self), name), None)
            if not ci.handle and isinstance(r, UObj):
                self.p = dict(r.p)
            return
        if p['attrs'].get('dependent'):
            raise MError('MATLAB:class:NoSetMethod', f"The Dependent property '{name}' of class '{ci.name}' has no set method.")
        self.p[name] = share(value)

    def propnames(self):
        return self.ci.prop_names()

    def display_lines(self):
        names = self.ci.prop_names()
        if not self.alive:
            return [f'  handle to deleted {self.ci.name}']
        lines = [f'  {self.ci.name} with properties:', '']
        if not names:
            return [f'  {self.ci.name} with no properties.']
        w = max(len(n) for n in names)
        from .display import summary
        for n in names:
            try:
                v = self.getprop(n)
                s = _inline(v, summary)
            except MError:
                s = '[]'
            lines.append(f'    {n.rjust(w)}: {s}')
        return lines

    def custom_display(self, name):
        """name = obj shown by the class's own disp or display method: the
        method prints, the name line first."""
        m = self.ci.find_method('display') or self.ci.find_method('disp')
        if m is None or not self.alive:
            return None
        from .runtime import run_sync, write
        from .display import FMT
        if self.ci.find_method('display') is None:
            write(f'{name} =\n' + ('\n' if FMT['spacing'] == 'loose' else ''))
        run_sync(m['fn'](0, self))
        return ''

    def delete_handle(self):
        if not self.alive or self.deleting:
            return
        self.deleting = True
        try:
            m = self.ci.find_method('delete')
            if m is not None:
                from .runtime import run_sync
                run_sync(m['fn'](0, self))
        finally:
            self.alive = False
            self.deleting = False


_IN_SETTER = {}


def _inline(v, summary):
    from .values import Char as C
    if isinstance(v, float):
        return f'{v:g}' if v == v else 'NaN'
    if isinstance(v, bool):
        return '1' if v else '0'
    if type(v) is C:
        return f"'{v.str()}'" if v.a.shape[0] <= 1 else summary(v)
    if type(v) is np.ndarray and v.size == 0:
        return '[]'
    if type(v) is np.ndarray and v.size <= 6 and v.ndim == 2 and v.shape[0] == 1 and v.dtype.kind in 'fiub':
        return '[' + ' '.join(f'{x:g}' for x in v.reshape(-1).astype(float)) + ']'
    return summary(v)


class BoundStatic(FH):
    __slots__ = ('mname', 'fn')

    def __init__(self, mname, fn):
        self.mname = mname
        self.fn = fn

    def text(self):
        return '@' + self.mname

    def name(self):
        return self.mname

    async def acall(self, nargout, *args):
        return await self.fn(nargout, *args)

    def scall(self, nargout, *args):
        from .runtime import run_sync
        return run_sync(self.acall(nargout, *args))


# ---- reading a classdef file -----------------------------------------------------------------------------------

_BLOCK = {'if', 'for', 'while', 'switch', 'try', 'function', 'parfor', 'spmd'}
_SECTIONS = {'properties', 'methods', 'events', 'enumeration'}


def is_classdef(text):
    for t in tokenize(text, keep_comments=False):
        if t.k == 'nl':
            continue
        return t.k == 'kw' and t.v == 'classdef'
    return False


def _attrs(text):
    """'(Access = private, Static)' as {'access': 'private', 'static': True}."""
    out = {}
    t = text.strip()
    if t.startswith('(') and t.endswith(')'):
        t = t[1:-1]
    for part in [p.strip() for p in re.split(r',(?![^{]*\})', t) if p.strip()]:
        if '=' in part:
            k, v = part.split('=', 1)
            v = v.strip().strip("'\"")
            vl = v.lower()
            out[k.strip().lower()] = True if vl == 'true' else False if vl == 'false' else v
        else:
            neg = part.startswith('~')
            out[part.lstrip('~').strip().lower()] = not neg
    return out


def _strip_comment(line):
    out = []
    q = None
    prev = ''
    for ch in line:
        if q:
            out.append(ch)
            if ch == q:
                q = None
        else:
            if ch == '%':
                break
            if ch == '"' or (ch == "'" and (not prev.strip() or prev in '=([{,;')):
                q = ch
            out.append(ch)
        if not ch.isspace():
            prev = ch
    return ''.join(out)


_DECL = re.compile(r'^\s*([A-Za-z]\w*)\s*(\([^)]*\))?\s*([A-Za-z][\w.]*)?\s*(\{.*?\})?\s*(?:=\s*(.*?))?\s*;?\s*$')


def _prop_lines(body):
    lines = []
    cur = ''
    for raw in body.split('\n'):
        s = _strip_comment(raw)
        if s.rstrip().endswith('...'):
            cur += s.rstrip()[:-3] + ' '
            continue
        cur += s
        if cur.strip():
            lines.append(cur.strip())
        cur = ''
    return lines


class Spec:
    def __init__(self):
        self.name = ''
        self.attrs = {}
        self.supers = []
        self.props = []      # (name, default_text, attrs, cls)
        self.methods = []    # (name, text, attrs, line)
        self.events = []
        self.enum = []


def parse(text, path=''):
    toks = tokenize(text, keep_comments=False)
    sp = Spec()
    i = 0
    while i < len(toks) and toks[i].k == 'nl':
        i += 1
    if i >= len(toks) or toks[i].v != 'classdef':
        raise MError('MATLAB:class:NotClassdef', 'The file does not start with classdef.')
    j = i + 1
    while j < len(toks) and toks[j].k != 'nl':
        j += 1
    header = text[toks[i].end:toks[j].pos if j < len(toks) else len(text)]
    header = _strip_comment(header).strip()
    m = re.match(r'^(\([^)]*\))?\s*([A-Za-z][\w.]*)\s*(?:<\s*(.*))?$', header)
    if not m:
        raise MError('MATLAB:class:BadHeader', f"The classdef line '{header}' is not one that is read here.")
    sp.attrs = _attrs(m.group(1) or '')
    sp.name = m.group(2)
    sp.supers = [s.strip() for s in (m.group(3) or '').split('&') if s.strip()]
    k = j
    n = len(toks)

    def stmt_start(idx):
        return idx == 0 or toks[idx - 1].k == 'nl' or (toks[idx - 1].k == 'op' and toks[idx - 1].v in (';', ','))

    while k < n:
        t = toks[k]
        name = t.v if t.k == 'id' else (t.v[0] if t.k == 'cmd' else None)
        if t.k == 'kw' and t.v == 'end':
            break      # the classdef's own end
        if name in _SECTIONS and stmt_start(k):
            if t.k == 'cmd':
                attrs = _attrs('(' + ', '.join(t.v[1]) + ')')
                k += 1
            else:
                k += 1
                attrs = {}
                if k < n and toks[k].k == 'op' and toks[k].v == '(':
                    depth = 0
                    st = k
                    while k < n:
                        if toks[k].k == 'op' and toks[k].v == '(':
                            depth += 1
                        elif toks[k].k == 'op' and toks[k].v == ')':
                            depth -= 1
                            if depth == 0:
                                break
                        k += 1
                    attrs = _attrs(text[toks[st].pos:toks[k].end])
                    k += 1
            body_start = toks[k].pos if k < n else len(text)
            if name == 'methods':
                k = _read_methods(text, toks, k, sp, attrs)
            else:
                # up to this section's end
                depth = 0
                while k < n:
                    tk = toks[k]
                    if tk.k == 'op' and tk.v in '([{':
                        depth += 1
                    elif tk.k == 'op' and tk.v in ')]}':
                        depth -= 1
                    elif tk.k == 'kw' and tk.v == 'end' and depth == 0:
                        break
                    k += 1
                body = text[body_start:toks[k].pos if k < n else len(text)]
                if name == 'properties':
                    for line in _prop_lines(body):
                        d = _DECL.match(line)
                        if not d:
                            raise MError('MATLAB:class:BadProperty', f"The property line '{line}' of class {sp.name} is not one that is read here.")
                        cls_ = d.group(3)
                        sp.props.append((d.group(1), d.group(5), attrs, cls_))
                elif name == 'events':
                    for line in _prop_lines(body):
                        sp.events += [w for w in re.split(r'[\s,;]+', line) if w]
                else:
                    for line in _prop_lines(body):
                        e = re.match(r'^([A-Za-z]\w*)\s*(\((.*)\))?', line)
                        if e:
                            sp.enum.append((e.group(1), e.group(3)))
                k += 1
            continue
        k += 1
    return sp


def _read_methods(text, toks, k, sp, attrs):
    """The functions of a methods section, up to its end: (name, text, attrs, line)."""
    n = len(toks)
    while k < n:
        t = toks[k]
        if t.k == 'kw' and t.v == 'end':
            return k + 1
        if t.k == 'kw' and t.v == 'function':
            start = k
            depth = 0
            br = 0
            k += 1
            stack = 1
            while k < n:
                tk = toks[k]
                if tk.k == 'op' and tk.v in '([{':
                    br += 1
                elif tk.k == 'op' and tk.v in ')]}':
                    br -= 1
                elif tk.k == 'kw' and br == 0:
                    if tk.v in _BLOCK:
                        stack += 1
                    elif tk.v == 'end':
                        stack -= 1
                        if stack == 0:
                            break
                k += 1
            ftext = text[toks[start].pos:toks[k].end if k < n else len(text)]
            hm = re.match(r'function\s+(?:(\[[^\]]*\]|[A-Za-z]\w*)\s*=\s*)?([A-Za-z][\w.]*)', ftext)
            if hm:
                sp.methods.append((hm.group(2), ftext, attrs, toks[start].line))
            k += 1
            continue
        if t.k == 'id' and t.v not in ('function',):
            # a method's signature with its code in a file of its own: not read here
            pass
        k += 1
    return k


# ---- making the class ---------------------------------------------------------------------------------------------

def _rename(ftext, name, cls_name, is_ctor):
    """A method's text with its new name; a constructor taking the object first."""
    hm = re.match(r'(function\s+)(?:(\[[^\]]*\]|[A-Za-z]\w*)(\s*=\s*))?([A-Za-z][\w.]*)(\s*\(([^)]*)\))?', ftext)
    pyname = 'M__' + name.replace('.', '__')
    outs = hm.group(2)
    params = hm.group(6) if hm.group(5) else ''
    rest = ftext[hm.end():]
    if is_ctor:
        out_name = outs.strip('[] ').split(',')[0].strip() if outs else 'plabobj'
        new_params = 'plabself' + (', ' + params if params.strip() else '')
        head = f'function {out_name} = {pyname}({new_params}); {out_name} = plabself;'
        # the object passed first is not one of the constructor's arguments
        edits = [(tk.pos, tk.end) for tk in tokenize(rest, keep_comments=True) if tk.k == 'id' and tk.v == 'nargin']
        for s, e in reversed(edits):
            rest = rest[:s] + '(nargin-1)' + rest[e:]
        return head + rest, out_name
    head = f"function {(outs + ' = ') if outs else ''}{pyname}{'(' + params + ')' if hm.group(5) else ''}"
    return head + rest, None


def _super_calls(ftext, ctor_out):
    """obj@Super(args) and method@Super(obj, args) as plabSuperCall('Super', ...)."""
    toks = tokenize(ftext, keep_comments=True)
    edits = []
    for i in range(len(toks) - 2):
        a, at, b = toks[i], toks[i + 1], toks[i + 2]
        if a.k == 'id' and at.k == 'op' and at.v == '@' and at.pos == a.end and b.k == 'id' and b.pos == at.end:
            # the superclass name may be dotted
            j = i + 2
            sup = b.v
            end = b.end
            while j + 2 < len(toks) and toks[j + 1].k == 'op' and toks[j + 1].v == '.' and toks[j + 2].k == 'id' and toks[j + 1].pos == end:
                sup += '.' + toks[j + 2].v
                end = toks[j + 2].end
                j += 2
            has_args = j + 1 < len(toks) and toks[j + 1].k == 'op' and toks[j + 1].v == '(' and toks[j + 1].pos == end
            if ctor_out and a.v == ctor_out:
                rep = f"plabSuperCall('{sup}', {a.v}" + (', ' if has_args else ')')
            else:
                rep = f"plabSuperCall('{sup}.{a.v}'" + (', ' if has_args else ')')
            edits.append((a.pos, end + (1 if has_args else 0), rep))
    for s, e, r in reversed(edits):
        ftext = ftext[:s] + r + ftext[e:]
    return ftext


def methods_text(sp, name):
    """The methods of a parsed class as one function file, renamed for the
    class, each at its own line of the classdef file; and (name, attributes,
    is the constructor) for each."""
    chunks = []
    line = 1
    meta = []
    for mname, ftext, attrs, fline in sp.methods:
        is_ctor = mname == name
        new_text, ctor_out = _rename(ftext, mname, name, is_ctor)
        new_text = _super_calls(new_text, ctor_out)
        if fline > line:
            chunks.append('\n' * (fline - line))
            line = fline
        chunks.append(new_text + '\n')
        line += new_text.count('\n') + 1
        meta.append((mname, attrs, is_ctor))
    return ''.join(chunks), meta


def build(path, text, R):
    """The class of a classdef file, its methods compiled."""
    import os
    sp = parse(text, path)
    name = os.path.splitext(os.path.basename(path))[0]
    ci = ClassInfo(name, path)
    ci.attrs = sp.attrs
    for s in sp.supers:
        if s in HANDLE_BASES or s.startswith('matlab.'):
            ci.base_names.append(s)
            ci.handle = True
            continue
        sci = load_class(s, R)
        if sci is None:
            raise MError('MATLAB:class:SuperClassNotFound', f"The superclass '{s}' of class '{name}' cannot be found.")
        ci.supers.append(sci)
        ci.handle = ci.handle or sci.handle
    ci.events = list(sp.events)
    CLASSES[name] = ci
    # the methods, compiled as one module
    src_text, meta = methods_text(sp, name)
    overridden = [m for m, a, c in meta if not c and not m.startswith(('get.', 'set.')) and m in R.BUILTINS]
    for m in overridden:
        install_override(m, R)
    if meta:
        from .compiler import compile_source
        src, linemap, prog = compile_source(src_text, R.BUILTINS, kind='file', user_funcs=R._user_file, modname=name, path=path)
        code = compile(src, f'<plab:{path}>', 'exec')
        ns = R.make_ns(path)
        exec(code, ns)
        mod = R.CompiledModule(path, name, src_text, src, linemap, 'class', ns)
        mod.prog = prog
        R.MODULES[f'<plab:{path}>'] = mod
        nouts = {}
        for mname, ftext, attrs, fline in sp.methods:
            hm = re.match(r'function\s+(?:(\[[^\]]*\]|[A-Za-z]\w*)\s*=\s*)?', ftext)
            outs = hm.group(1) if hm else None
            names = [o for o in re.split(r'[\s,]+', outs.strip('[] ')) if o] if outs else []
            nouts[mname] = 99 if 'varargout' in names else len(names)
        for mname, attrs, is_ctor in meta:
            fn = ns['LF_M__' + mname.replace('.', '__')]
            try:
                fn.nouts = nouts.get(mname, 99)
            except AttributeError:
                pass
            if is_ctor:
                ci.ctor = fn
            elif mname.startswith('get.'):
                ci.getters[mname[4:]] = fn
            elif mname.startswith('set.'):
                ci.setters[mname[4:]] = fn
            else:
                ci.methods[mname] = {'fn': fn, 'static': bool(attrs.get('static')), 'attrs': attrs}
    # the properties' defaults, worked out once
    for pname, default, attrs, cls_ in sp.props:
        val = NOVAL
        if default:
            val = _evaluate(default, R, name)
        ci.props[pname] = {'default': val if val is not NOVAL else EMPTY(), 'attrs': attrs, 'cls': cls_, 'has_default': val is not NOVAL}
    return ci


def _evaluate(expr, R, cname):
    W = R.Workspace(f'{cname} properties', ())
    try:
        fn, _ = R.compile_command(f'plabdefault = {expr};', W)
        R.run_sync(fn(W))
    except MError as e:
        raise MError('MATLAB:class:DefaultValue', f"The default value of a property of class {cname}, {expr}, cannot be worked out: {e.message if hasattr(e, 'message') else e}")
    return W['plabdefault']


def load_class(name, R):
    """The class of that name, from its file as it is now (load_file compiles
    a changed file again)."""
    p = R.find_file(name)
    if p is None:
        return None
    mod = R.load_file(p)
    return getattr(mod, 'classinfo', None)


def _fresh(ci, R):
    return True


def new_object(ci):
    o = UObj(ci)
    _init_props(o, ci)
    return o


def _init_props(o, ci):
    for s in ci.supers:
        _init_props(o, s)
    for k, p in ci.props.items():
        if not p['attrs'].get('dependent') and not p['attrs'].get('constant'):
            o.p[k] = share(p['default'])


async def construct(ci, nargout, args, obj=None):
    o = obj if obj is not None else new_object(ci)
    if ci.ctor is not None:
        # asked for no output (an app's constructor clears it then), none is given
        r = await ci.ctor(nargout, o, *args)
        if nargout == 0 and obj is None:
            return r if isinstance(r, UObj) else None
        o = r if isinstance(r, UObj) else o
    else:
        if args:
            # no constructor of its own: a superclass's takes the arguments
            for s in ci.supers:
                if s.ctor is not None:
                    o = await construct(s, 1, args, o)
                    break
        elif ci.supers:
            for s in ci.supers:
                if s.ctor is not None:
                    o = await construct(s, 1, (), o)
    return o


def install_override(name, R):
    """A class defines a method with a builtin's name: a dispatcher goes in
    front of the builtin, so that an object among its arguments goes to the
    class's method. A builtin compiled code awaits keeps being awaited; for
    the others the method runs to its end at once (it cannot wait for input,
    which a disp or a plus never does)."""
    if name in _OVERRIDDEN:
        return
    info = R.BUILTINS.get(name)
    if info is None:
        return
    orig, was_aw, ws = info.fn, info.aw, info.ws

    def method_of(args):
        for x in args:
            if type(x) is UObj:
                m = x.ci.find_method(name)
                if m is not None:
                    return m
        return None
    if was_aw:
        async def d(*a):
            args = a[2:] if ws else a[1:]
            m = method_of(args)
            if m is not None:
                return await m['fn'](a[1] if ws else a[0], *args)
            return await orig(*a)
    else:
        def d(*a):
            args = a[2:] if ws else a[1:]
            m = method_of(args)
            if m is not None:
                return R.run_sync(m['fn'](a[1] if ws else a[0], *args))
            return orig(*a)
    info.fn = d
    _OVERRIDDEN.add(name)
    from .compiler import pyname
    if '.' not in name:
        setattr(R.B, pyname(name), d)


async def dispatch(name, nargout, args):
    """method(obj, ...): the method of the first object among the arguments that has one, or NOVAL."""
    for x in args:
        if type(x) is UObj:
            m = x.ci.find_method(name)
            if m is not None:
                return await m['fn'](nargout, *args)
            break
    return NOVAL


async def static_or_const(base, rest, nargout, args, R):
    """ClassName.method(...) and ClassName.Constant: NOVAL when base is no class."""
    target = R.find_file(base)
    if target is None:
        return NOVAL
    mod = R.load_file(target)
    ci = getattr(mod, 'classinfo', None)
    if ci is None:
        return NOVAL
    m = ci.find_method(rest)
    if m is not None:
        return await m['fn'](nargout, *args)
    p = ci.find_prop(rest)
    if p is not None and p['attrs'].get('constant'):
        v = p['default']
        from .index import idx
        return idx(v, args) if args else v
    raise MError('MATLAB:subscripting:classHasNoPropertyOrMethod', f"The class {base} has no Constant property or Static method named '{rest}'.")


# ---- operators ------------------------------------------------------------------------------------------------------

_OPNAMES = {'+': 'plus', '-': 'minus', '.*': 'times', './': 'rdivide', '.\\': 'ldivide', '.^': 'power', '*': 'mtimes', '/': 'mrdivide',
            '\\': 'mldivide', '^': 'mpower', '==': 'eq', '~=': 'ne', '<': 'lt', '<=': 'le', '>': 'gt', '>=': 'ge', '&': 'and', '|': 'or'}
_UNNAMES = {'-': 'uminus', '+': 'uplus', '~': 'not', ".'": 'transpose', "'": 'ctranspose'}


class _UOps:
    @staticmethod
    def binop(op, a, b):
        from .runtime import run_sync
        name = _OPNAMES[op]
        for x in (a, b):
            if type(x) is UObj:
                m = x.ci.find_method(name)
                if m is not None:
                    return run_sync(m['fn'](1, a, b))
        if op in ('==', '~=') and type(a) is UObj and type(b) is UObj and a.ci.handle:
            same = a is b
            return same if op == '==' else not same
        cls = (a if type(a) is UObj else b).ci.name
        raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for operands of type '{cls}'.")

    @staticmethod
    def unop(op, a):
        from .runtime import run_sync
        name = _UNNAMES[op]
        m = a.ci.find_method(name)
        if m is not None:
            return run_sync(m['fn'](1, a))
        if op in (".'", "'"):
            return a
        raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for operands of type '{a.ci.name}'.")


def install():
    from . import ops
    ops.UOBJ = UObj
    ops.UOPS = _UOps


install()
