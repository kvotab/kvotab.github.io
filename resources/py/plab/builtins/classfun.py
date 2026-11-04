"""Functions of objects of the language's own classes (classdef.py): super
calls, properties, methods, events and listeners, isvalid, copy; and what
matlab.apps.AppBase gives an app: createCallbackFcn, registerApp and
runStartupFcn.
"""
import numpy as np

from . import bi, REG
from ._util import err, opt_str, is_str, sval
from ..values import MError, Char, Cell, Struct, FH, Obj, NOVAL, EMPTY, py_str, share
from .. import runtime as R
from .. import classdef as CD


def _obj(v, fn):
    if type(v) is not CD.UObj:
        raise err('MATLAB:class:NotAnObject', f'{fn} takes an object of a class.', fn)
    return v


@bi('plabSuperCall', aw=True, arr=False)
async def plabSuperCall(nargout, *args):
    """obj@Super(args) and method@Super(obj, args), as classdef.py writes them."""
    what = py_str(args[0])
    rest = args[1:]
    if '.' in what and what.rsplit('.', 1)[0] not in CD.HANDLE_BASES and not what.startswith('matlab.'):
        sup, mname = what.rsplit('.', 1)
        ci = CD.load_class(sup, R)
        if ci is not None:
            m = ci.find_method(mname)
            if m is None:
                raise err('MATLAB:class:MethodNotFound', f"The class {sup} has no method {mname}.", mname)
            return await m['fn'](nargout, *rest)
    if what == 'matlab.mixin.Copyable.copyElement':
        # copyElement@matlab.mixin.Copyable(obj): the shallow copy a subclass's copyElement starts from
        return shallow_copy(_obj(rest[0], 'copyElement'))
    sup = what
    obj = rest[0]
    if sup in CD.HANDLE_BASES or sup.startswith('matlab.'):
        return obj
    ci = CD.load_class(sup, R)
    if ci is None:
        raise err('MATLAB:class:SuperClassNotFound', f"The superclass '{sup}' cannot be found.", 'plabSuperCall')
    return await CD.construct(ci, 1, rest[1:], obj)


@bi('isobject')
def isobject(nargout, *args):
    return type(args[0]) is CD.UObj


@bi('properties', arr=False)
def properties(nargout, *args):
    v = args[0]
    if type(v) is CD.UObj:
        names = v.ci.prop_names()
        cname = v.ci.name
    elif is_str(v):
        ci = CD.load_class(py_str(v), R)
        if ci is None:
            raise err('MATLAB:class:NotFound', f"No class named '{py_str(v)}'.", 'properties')
        names, cname = ci.prop_names(), ci.name
    elif isinstance(v, Obj):
        names, cname = v.propnames(), getattr(v, 'cls', 'object')
    else:
        raise err('MATLAB:class:NotAnObject', 'properties takes an object or a class name.', 'properties')
    if nargout:
        return Cell.of_list([Char.of(n) for n in names], (len(names), 1))
    R.write(f'\nProperties for class {cname}:\n\n' + ''.join(f'    {n}\n' for n in names) + '\n')
    return None


def _all_methods(ci):
    names = []
    for s in ci.supers:
        for n in _all_methods(s):
            if n not in names:
                names.append(n)
    for n in ci.methods:
        if n not in names:
            names.append(n)
    return names


@bi('methods', arr=False)
def methods_(nargout, *args):
    v = args[0]
    ci = v.ci if type(v) is CD.UObj else (CD.load_class(py_str(v), R) if is_str(v) else None)
    if ci is None:
        raise err('MATLAB:class:NotFound', 'methods takes an object or a class name.', 'methods')
    names = sorted(_all_methods(ci) + [ci.name])
    if nargout:
        return Cell.of_list([Char.of(n) for n in names], (len(names), 1))
    R.write(f'\nMethods for class {ci.name}:\n\n' + '  '.join(names) + '\n\n')
    return None


@bi('import', ws=True, arr=False)
def import_(W, nargout, *args):
    """import pkg.* and import pkg.name: bare names in this workspace then
    reach the package's functions and classes; import alone lists them."""
    imps = W.imports if W.imports is not None else []
    if not args:
        if nargout:
            return Cell.of_list([Char.of(x) for x in imps], (len(imps), 1))
        R.write(''.join(f'    {x}\n' for x in imps) if imps else '')
        return None
    for a in args:
        s = sval(a, 'package name', 'import').strip()
        import re
        if not re.fullmatch(r'[A-Za-z]\w*(\.[A-Za-z]\w*)*(\.\*)?', s) or '.' not in s:
            raise err('MATLAB:import:InvalidName', f"'{s}' is not a name to import: write pkg.* or pkg.name.", 'import')
        if s not in imps:
            imps.append(s)
    W.imports = imps
    return None


@bi('enumeration', arr=False)
def enumeration(nargout, *args):
    if not args:
        raise err('MATLAB:minrhs', 'enumeration takes a class name or an enumeration member.', 'enumeration')
    v = args[0]
    ci = v.ci if type(v) is CD.UObj else (v.a.flat[0].ci if CD.is_enum(v) else (CD.load_class(py_str(v), R) if is_str(v) else None))
    if ci is None:
        raise err('MATLAB:class:NotFound', 'enumeration takes a class name or an enumeration member.', 'enumeration')
    members = CD.enum_members(ci) if ci.enum else []
    names = [m.enum for m in members]
    if not nargout:
        R.write(f"\nEnumeration members for class '{ci.name}':\n\n" + ''.join(f'    {n}\n' for n in names) + '\n' if names
                else f"\nNo enumeration members for class '{ci.name}'.\n\n")
        return None
    from ..graphics_base import HArr
    m = HArr.of(members, col=True) if members else EMPTY()
    if nargout >= 2:
        return m, Cell.of_list([Char.of(n) for n in names], (len(names), 1))
    return m


@bi('ismethod')
def ismethod(nargout, *args):
    v = args[0]
    name = sval(args[1], 'method name', 'ismethod')
    return type(v) is CD.UObj and v.ci.find_method(name) is not None


_orig_isvalid = REG['isvalid'].fn if 'isvalid' in REG else None


@bi('isvalid', arr=False)
def isvalid(nargout, *args):
    v = args[0]
    if type(v) is CD.UObj:
        return v.alive
    if _orig_isvalid is not None:
        return _orig_isvalid(nargout, *args)
    return False


# ---- events -----------------------------------------------------------------------------------------------------

class Listener(Obj):
    """addlistener's listener: the object, the event and the callback."""
    __slots__ = ('src', 'event', 'cb', 'enabled')
    is_handle = True
    cls = 'event.listener'

    def __init__(self, src, event, cb):
        self.src, self.event, self.cb = src, event, cb
        self.enabled = True

    def getprop(self, name):
        n = name.lower()
        if n == 'enabled':
            return self.enabled
        if n == 'eventname':
            return Char.of(self.event)
        if n == 'source':
            return Cell.of_list([self.src], (1, 1))
        if n == 'callback':
            return self.cb
        return super().getprop(name)

    def setprop(self, name, value):
        if name.lower() == 'enabled':
            self.enabled = bool(np.all(np.asarray(value))) if not is_str(value) else py_str(value).lower() in ('on', 'true')
            return
        super().setprop(name, value)

    def propnames(self):
        return ['Source', 'EventName', 'Callback', 'Enabled']

    def delete_handle(self):
        lst = self.src.listeners.get(self.event, []) if type(self.src) is CD.UObj else []
        if self in lst:
            lst.remove(self)


def event_names(ci):
    """A class's events, its superclasses' after its own; a handle class has ObjectBeingDestroyed."""
    names = []
    for c in [ci] + list(ci.supers):
        for e in (c.events if c is ci else event_names(c)):
            if e not in names:
                names.append(e)
    if ci.handle and 'ObjectBeingDestroyed' not in names:
        names.append('ObjectBeingDestroyed')
    return names


@bi('events', arr=False)
def events(nargout, *args):
    """events(obj), events('ClassName'): the events the class has; with an
    output, their names as a column cell array."""
    if len(args) != 1:
        raise err('MATLAB:minrhs' if not args else 'MATLAB:TooManyInputs', 'events takes one object or class name.', 'events')
    v = args[0]
    if type(v) is CD.UObj:
        ci = v.ci
    elif is_str(v):
        ci = CD.load_class(py_str(v), R)
        if ci is None:
            raise err('MATLAB:class:NotFound', f"No class named '{py_str(v)}'.", 'events')
    else:
        raise err('MATLAB:class:NotAnObject', 'events takes an object or a class name.', 'events')
    names = event_names(ci)
    if nargout:
        return Cell.of_list([Char.of(n) for n in names], (len(names), 1))
    if not names:
        R.write(f'\nNo events for class {ci.name}.\n\n')
    else:
        R.write(f'\nEvents for class {ci.name}:\n\n' + ''.join(f'    {n}\n' for n in names) + '\n')
    return None


def shallow_copy(obj):
    """A new object of the class holding the same property values (handles in
    them shared), its NonCopyable properties at their defaults."""
    o = CD.UObj(obj.ci)
    for name, v in obj.p.items():
        p = obj.ci.find_prop(name)
        if p is not None and p['attrs'].get('noncopyable'):
            v = p['default']
        o.p[name] = share(v)
    return o


def _copyable(ci):
    return 'matlab.mixin.Copyable' in ci.all_names()


@bi('copy', aw=True, arr=False)
async def copy(nargout, *args):
    """b = copy(a): a copy of a handle object whose class derives from
    matlab.mixin.Copyable, made by its copyElement (a shallow copy unless the
    class overrides it); a datastore's copy, at the same place."""
    if len(args) != 1:
        raise err('MATLAB:minrhs' if not args else 'MATLAB:TooManyInputs', 'copy takes one object.', 'copy')
    v = args[0]
    from . import datastores as DS
    for test, handler in DS.COPY_HANDLERS:
        if test(v):
            return handler(1, v)
    if type(v) is CD.UObj:
        if not _copyable(v.ci):
            raise err('MATLAB:UndefinedFunction', f"Undefined function 'copy' for input arguments of type '{v.ci.name}': its class does not derive from matlab.mixin.Copyable.", 'copy')
        if not v.alive:
            raise err('MATLAB:class:InvalidHandle', 'Invalid or deleted object.', 'copy')
        m = v.ci.find_method('copyElement')
        if m is not None:
            return await m['fn'](1, v)
        return shallow_copy(v)
    raise err('MATLAB:UndefinedFunction', f"Undefined function 'copy' for input arguments of type '{getattr(v, 'cls', type(v).__name__)}'.", 'copy')


@bi('addlistener', 'listener', arr=False)
def addlistener(nargout, *args):
    src = args[0]
    ev = sval(args[1], 'event name', 'addlistener')
    cb = args[-1]
    if type(src) is not CD.UObj:
        raise err('MATLAB:class:NotAnObject', 'addlistener takes an object of a class with the event.', 'addlistener')
    names = event_names(src.ci)
    if ev not in names:
        raise err('MATLAB:class:InvalidEvent', f"The class {src.ci.name} has no event named '{ev}'.", 'addlistener')
    L = Listener(src, ev, cb)
    src.listeners.setdefault(ev, []).append(L)
    return L


@bi('notify', aw=True, arr=False)
async def notify(nargout, *args):
    src = _obj(args[0], 'notify')
    ev = sval(args[1], 'event name', 'notify')
    data = args[2] if len(args) > 2 else Struct.scalar({'Source': src, 'EventName': Char.of(ev)})
    if type(data) is Struct and 'EventName' not in data.f:
        d = {k: data.get1(k) for k in data.f}
        d.update({'Source': src, 'EventName': Char.of(ev)})
        data = Struct.scalar(d)
    for L in list(src.listeners.get(ev, [])):
        if L.enabled:
            from ..uievents import call as uicall
            await uicall(L.cb, src, data)
    return None


# ---- what an app's base class gives it ------------------------------------------------------------------------------

class AppCallback(FH):
    """createCallbackFcn: a component's callback that calls the app's method
    with the app (and the event data)."""
    __slots__ = ('app', 'fh', 'event')

    def __init__(self, app, fh, event):
        self.app, self.fh, self.event = app, fh, event

    def text(self):
        return f"@(source, event) {self.fh.name()}(app{', event' if self.event else ''})"

    def name(self):
        return self.fh.name()

    async def acall(self, nargout, *args):
        evt = args[1] if len(args) > 1 else EMPTY()
        if self.event:
            return await self.fh.acall(nargout, self.app, evt)
        return await self.fh.acall(nargout, self.app)

    def scall(self, nargout, *args):
        return R.run_sync(self.acall(nargout, *args))


@bi('createCallbackFcn', arr=False)
def createCallbackFcn(nargout, *args):
    app = _obj(args[0], 'createCallbackFcn')
    fh = args[1]
    if not isinstance(fh, FH):
        raise err('MATLAB:apps:createCallbackFcn', 'createCallbackFcn takes the app and a function handle.', 'createCallbackFcn')
    pass_event = bool(np.all(np.asarray(args[2]))) if len(args) > 2 else False
    return AppCallback(app, fh, pass_event)


@bi('registerApp', arr=False)
def registerApp(nargout, *args):
    app = _obj(args[0], 'registerApp')
    fig = args[1]
    if hasattr(fig, 'props'):
        def gone(src, evt, app=app):
            # the app's window closed or deleted: the app goes with it
            if app.alive and not app.deleting:
                try:
                    app.delete_handle()
                except MError:
                    app.alive = False
        if not fig.props.get('DeleteFcn'):
            fig.props['DeleteFcn'] = gone
    return None


@bi('runStartupFcn', aw=True, arr=False)
async def runStartupFcn(nargout, *args):
    app = _obj(args[0], 'runStartupFcn')
    fh = args[1]
    await fh.acall(0, app)
    return None
