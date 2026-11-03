"""Functions of objects of the language's own classes (classdef.py): super
calls, properties, methods, events and listeners, isvalid; and what
matlab.apps.AppBase gives an app: createCallbackFcn, registerApp and
runStartupFcn.
"""
import numpy as np

from . import bi, REG
from ._util import err, opt_str, is_str, sval
from ..values import MError, Char, Cell, Struct, FH, Obj, NOVAL, EMPTY, py_str
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


@bi('addlistener', 'listener', arr=False)
def addlistener(nargout, *args):
    src = args[0]
    ev = sval(args[1], 'event name', 'addlistener')
    cb = args[-1]
    if type(src) is not CD.UObj:
        raise err('MATLAB:class:NotAnObject', 'addlistener takes an object of a class with the event.', 'addlistener')
    names = [e for c in [src.ci] + src.ci.supers for e in c.events]
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
