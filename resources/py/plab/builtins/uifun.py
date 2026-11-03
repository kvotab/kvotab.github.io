"""User interfaces: controls, panels, tables, tabs, menus, context menus
and toolbars made in figures; the callbacks' gcbo and gcbf; waiting for
people (uiwait, waitfor); data kept with objects (guidata, setappdata);
the dialogs (msgbox and its kin, questdlg, inputdlg, listdlg, the file
pickers, waitbar); timers; and sound. The objects are in uiobjects, what
people do with them in uievents."""
import base64
import itertools
import math
import os

import numpy as np

from . import bi
from ._util import err, nargchk, sval, opt_str, opt_lower, num, is_str, cellstr_list, darr
from ..values import MError, Char, Cell, Struct, Str, FH, Obj, EMPTY, py_str, numel
from ..graphics_base import STORE, ROOT, GObj, Figure, Axes, Patch, HArr, gerr
from ..uiobjects import (UIControl, UIPanel, UIButtonGroup, UITable, UITabGroup, UITab, UIMenu, UIContextMenu, UIToolbar,
                         UIPushTool, UIToggleTool, lines_of)
from .. import uievents as E
from .. import runtime as R
from .graphics import gcf_, _handles


# ---- making the objects -------------------------------------------------------------------------------

def _one(v):
    if isinstance(v, HArr) and v.a.size == 1:
        v = v.a.flat[0]
    if type(v) is float or (isinstance(v, np.ndarray) and v.size == 1 and v.dtype.kind in 'fiu'):
        v = _handles(v)[0]
    return v


def _pairs(args, fn):
    """(parent given first or as 'Parent', the other name-value pairs)."""
    rest = list(args)
    parent = None
    if rest and not is_str(rest[0]) and type(rest[0]) is not Struct:
        parent = _one(rest.pop(0))
    if len(rest) == 1 and type(rest[0]) is Struct:
        s = rest[0]
        pairs = [(k, s.get1(k)) for k in s.f]
    else:
        if len(rest) % 2:
            raise err('MATLAB:hg:set:InvalidNumberOfInputs', 'Invalid parameter/value pair arguments.', fn)
        pairs = [(sval(rest[i], 'property name', fn), rest[i + 1]) for i in range(0, len(rest), 2)]
    for k, v in pairs:
        if k.lower() == 'parent':
            parent = _one(v)
    return parent, [(k, v) for k, v in pairs if k.lower() != 'parent']


def _make(cls, parent, pairs, fn, kinds):
    if not isinstance(parent, GObj) or not parent.valid:
        raise err('MATLAB:hg:InvalidParent', f'The parent of a {cls.TYPE} must be a valid graphics object.', fn)
    if parent.TYPE not in kinds:
        raise err('MATLAB:hg:InvalidParent', f'A {cls.TYPE} cannot be a child of a {parent.TYPE}.', fn)
    h = cls(parent)
    try:
        for k, v in pairs:
            h.setprop(k, v)
    except MError:
        h.delete_handle()
        raise
    h.touch()
    E.created(h)
    return h


_HOLDERS = ('figure', 'uipanel', 'uibuttongroup', 'uitab')


@bi('uicontrol', arr=False)
def uicontrol(nargout, *args):
    parent, pairs = _pairs(args, 'uicontrol')
    if isinstance(parent, UIControl) and not pairs:
        R.EVENT_HOOK[0] and R.EVENT_HOOK[0]({'type': 'focus', 'id': parent.id})
        return parent if nargout else None
    h = _make(UIControl, parent or gcf_(), pairs, 'uicontrol', _HOLDERS)
    p = h.parent
    if p.TYPE == 'uibuttongroup' and h.props['Style'] in ('radiobutton', 'togglebutton'):
        others = [b for b in p.buttons() if b is not h]
        if not any(b.selected() == [b.props['Max']] for b in others):
            p.select(h)
        elif h.selected() == [h.props['Max']]:
            p.select(h)
    return h if nargout else None


@bi('uipanel', arr=False)
def uipanel(nargout, *args):
    parent, pairs = _pairs(args, 'uipanel')
    h = _make(UIPanel, parent or gcf_(), pairs, 'uipanel', _HOLDERS)
    return h if nargout else None


@bi('uibuttongroup', arr=False)
def uibuttongroup(nargout, *args):
    parent, pairs = _pairs(args, 'uibuttongroup')
    h = _make(UIButtonGroup, parent or gcf_(), pairs, 'uibuttongroup', _HOLDERS)
    return h if nargout else None


@bi('uitable', arr=False)
def uitable(nargout, *args):
    parent, pairs = _pairs(args, 'uitable')
    h = _make(UITable, parent or gcf_(), pairs, 'uitable', _HOLDERS)
    return h if nargout else None


@bi('uitabgroup', arr=False)
def uitabgroup(nargout, *args):
    parent, pairs = _pairs(args, 'uitabgroup')
    h = _make(UITabGroup, parent or gcf_(), pairs, 'uitabgroup', _HOLDERS)
    return h if nargout else None


@bi('uitab', arr=False)
def uitab(nargout, *args):
    parent, pairs = _pairs(args, 'uitab')
    if parent is None:
        parent = _make(UITabGroup, gcf_(), [], 'uitab', _HOLDERS)
    h = _make(UITab, parent, pairs, 'uitab', ('uitabgroup',))
    return h if nargout else None


@bi('uimenu', arr=False)
def uimenu(nargout, *args):
    parent, pairs = _pairs(args, 'uimenu')
    h = _make(UIMenu, parent or gcf_(), pairs, 'uimenu', ('figure', 'uimenu', 'uicontextmenu'))
    return h if nargout else None


@bi('uicontextmenu', arr=False)
def uicontextmenu(nargout, *args):
    parent, pairs = _pairs(args, 'uicontextmenu')
    h = _make(UIContextMenu, parent or gcf_(), pairs, 'uicontextmenu', ('figure',))
    return h if nargout else None


@bi('uitoolbar', arr=False)
def uitoolbar(nargout, *args):
    parent, pairs = _pairs(args, 'uitoolbar')
    h = _make(UIToolbar, parent or gcf_(), pairs, 'uitoolbar', ('figure',))
    return h if nargout else None


def _toolbar(parent):
    if parent is not None:
        return parent
    f = gcf_()
    bars = [c for c in reversed(f.children) if c.valid and c.TYPE == 'uitoolbar']
    return bars[0] if bars else _make(UIToolbar, f, [], 'uitoolbar', ('figure',))


@bi('uipushtool', arr=False)
def uipushtool(nargout, *args):
    parent, pairs = _pairs(args, 'uipushtool')
    h = _make(UIPushTool, _toolbar(parent), pairs, 'uipushtool', ('uitoolbar',))
    return h if nargout else None


@bi('uitoggletool', arr=False)
def uitoggletool(nargout, *args):
    parent, pairs = _pairs(args, 'uitoggletool')
    h = _make(UIToggleTool, _toolbar(parent), pairs, 'uitoggletool', ('uitoolbar',))
    return h if nargout else None


# ---- callbacks ---------------------------------------------------------------------------------------

@bi('gcbo', nout=2, arr=False)
def gcbo(nargout, *args):
    o, f = E.gcbo(), E.gcbf()
    o = o if o is not None else EMPTY()
    if nargout > 1:
        return o, (f if f is not None else EMPTY())
    return o


@bi('gcbf', arr=False)
def gcbf(nargout, *args):
    f = E.gcbf()
    return f if f is not None else EMPTY()


@bi('closereq', arr=False)
def closereq(nargout, *args):
    f = E.gcbf() or STORE.current
    if f is not None and f.valid:
        f.delete_handle()
    return None


@bi('uiwait', aw=True, arr=False)
async def uiwait(nargout, *args):
    h = _one(args[0]) if args else gcf_()
    timeout = float(num(args[1])) if len(args) > 1 else None
    if not isinstance(h, GObj):
        raise err('MATLAB:uiwait:InvalidInput', 'uiwait waits for a figure.', 'uiwait')
    h.resumed = False
    await E.wait_until(lambda: not h.valid or h.resumed, timeout)
    return None


@bi('uiresume', arr=False)
def uiresume(nargout, *args):
    h = _one(args[0]) if args else gcf_()
    if isinstance(h, GObj):
        h.resumed = True
    return None


@bi('waitfor', aw=True, arr=False)
async def waitfor(nargout, *args):
    nargchk(args, 1, 3, 'waitfor')
    h = _one(args[0])
    if not isinstance(h, (GObj, Obj)) or not getattr(h, 'valid', True):
        return None
    if len(args) == 1:
        await E.wait_until(lambda: not h.valid)
        return None
    from .core import _equal
    prop = sval(args[1], 'property name', 'waitfor')
    first = h.getprop(prop)
    if len(args) > 2:
        want = args[2]
        await E.wait_until(lambda: not h.valid or _equal(h.getprop(prop), want, False))
    else:
        await E.wait_until(lambda: not h.valid or not _equal(h.getprop(prop), first, False))
    return None


# ---- data kept with an object ---------------------------------------------------------------------------

def _store_of(h):
    h = _one(h)
    if not hasattr(h, 'props') or not getattr(h, 'valid', True):
        raise err('MATLAB:hg:InvalidHandle', 'Invalid or deleted object.')
    d = getattr(h, 'appdata', None)
    if d is None:
        d = {}
        try:
            h.appdata = d
        except AttributeError:
            raise err('MATLAB:appdata:noAppdata', 'This object cannot keep application data.')
    return d


@bi('setappdata', arr=False)
def setappdata(nargout, *args):
    nargchk(args, 3, 3, 'setappdata')
    _store_of(args[0])[sval(args[1], 'name', 'setappdata')] = args[2]
    return None


@bi('getappdata', arr=False)
def getappdata(nargout, *args):
    nargchk(args, 1, 2, 'getappdata')
    d = _store_of(args[0])
    if len(args) == 1:
        return Struct.scalar(dict(d))
    return d.get(sval(args[1], 'name', 'getappdata'), EMPTY())


@bi('isappdata')
def isappdata(nargout, *args):
    nargchk(args, 2, 2, 'isappdata')
    names = cellstr_list(args[1]) if type(args[1]) is Cell else [sval(args[1], 'name', 'isappdata')]
    d = _store_of(args[0])
    res = [n in d for n in names]
    return res[0] if len(res) == 1 else np.array([res])


@bi('rmappdata', arr=False)
def rmappdata(nargout, *args):
    nargchk(args, 2, None, 'rmappdata')
    d = _store_of(args[0])
    for a in args[1:]:
        n = sval(a, 'name', 'rmappdata')
        if n not in d:
            raise err('MATLAB:rmappdata:nameNotFound', f"Application data '{n}' was not found.", 'rmappdata')
        del d[n]
    return None


@bi('guidata', arr=False)
def guidata(nargout, *args):
    nargchk(args, 1, 2, 'guidata')
    h = _one(args[0])
    f = h.figure() if isinstance(h, GObj) else None
    if f is None:
        raise err('MATLAB:guidata:InvalidInput', 'guidata needs a graphics object in a figure.', 'guidata')
    d = _store_of(f)
    if len(args) == 2:
        d['UsedByGUIData_m'] = args[1]
        return None
    return d.get('UsedByGUIData_m', EMPTY())


# ---- windows ---------------------------------------------------------------------------------------------

@bi('movegui', arr=False)
def movegui(nargout, *args):
    h = _one(args[0]) if args and not is_str(args[0]) else gcf_()
    where = opt_str(args[-1]) if args and is_str(args[-1]) else 'onscreen'
    f = h.figure() if isinstance(h, GObj) else None
    if f is not None:
        R.flush_figures()
        R.EVENT_HOOK[0] and R.EVENT_HOOK[0]({'type': 'movegui', 'figure': f.id, 'where': where.lower()})
    return None


@bi('inspect', arr=False)
def inspect_(nargout, *args):
    nargchk(args, 0, 1, 'inspect')
    try:
        h = _one(args[0]) if args else gcf_()
    except MError:
        h = None
    if not isinstance(h, GObj) or not h.valid or h.figure() is None:
        raise err('MATLAB:inspect:invalidInput', 'The input must be a graphics object in a figure.', 'inspect')
    R.flush_figures()
    R.EVENT_HOOK[0] and R.EVENT_HOOK[0]({'type': 'inspect', 'figure': h.figure().id, 'id': h.id})
    return None


@bi('plotedit', arr=False)
def plotedit(nargout, *args):
    nargchk(args, 0, 2, 'plotedit')
    rest = list(args)
    f = gcf_()
    if rest and not is_str(rest[0]):
        try:
            h = _one(rest.pop(0))
        except MError:
            h = None
        if not isinstance(h, GObj) or not h.valid or h.figure() is None:
            raise err('MATLAB:plotedit:invalidInput', 'The input must be a figure.', 'plotedit')
        f = h.figure()
    on = None
    if rest:
        s = opt_lower(rest[0], 'plotedit')
        if s not in ('on', 'off'):
            raise err('MATLAB:plotedit:invalidInput', "Use 'on' or 'off'.", 'plotedit')
        on = s == 'on'
    R.flush_figures()
    R.EVENT_HOOK[0] and R.EVENT_HOOK[0]({'type': 'plotedit', 'figure': f.id, 'on': on})
    return None


@bi('uistack', arr=False)
def uistack(nargout, *args):
    nargchk(args, 1, 3, 'uistack')
    hs = [h for h in _handles(args[0]) if isinstance(h, GObj) and h.parent is not None]
    how = opt_lower(args[1]) if len(args) > 1 else 'up'
    step = int(num(args[2])) if len(args) > 2 else 1
    for h in hs:
        kids = h.parent.children            # first is on top
        i = kids.index(h)
        kids.pop(i)
        j = {'top': 0, 'bottom': len(kids), 'up': max(0, i - step), 'down': min(len(kids), i + step)}.get(how)
        if j is None:
            raise err('MATLAB:uistack:InvalidOption', f"Unknown option '{how}': use 'up', 'down', 'top' or 'bottom'.", 'uistack')
        kids.insert(j, h)
        h.touch()
    return None


@bi('helpwin', 'doc', arr=False)
def helpwin(nargout, *args):
    name = sval(args[0], 'name', 'helpwin') if args else ''
    R.EVENT_HOOK[0] and R.EVENT_HOOK[0]({'type': 'help', 'name': name})
    return None


# ---- dialogs that are figures ----------------------------------------------------------------------------

_dialogs = itertools.count(1)
_LAST_WAITBAR = [None]


def dialog_figure(title, w, h, modal=False):
    """A figure for a dialog: no number, never the current figure, no
    menus or tools; centred on the desktop."""
    f = Figure(-next(_dialogs))
    scr = np.asarray(ROOT.props['ScreenSize'], float).reshape(-1)
    f.props.update(Name=title, MenuBar='none', ToolBar='none', Resize=False, WindowStyle='modal' if modal else 'normal',
                   Position=np.array([[(scr[2] - w) / 2, (scr[3] - h) / 2, float(w), float(h)]]))
    return f


def _wrap(lines, width=75):
    """A message's lines broken at spaces to at most width letters, as a
    message box wraps them (help text, 75 wide, keeps its lines)."""
    out = []
    for line in lines:
        while len(line) > width:
            cut = line.rfind(' ', 0, width + 1)
            if cut <= 0:
                cut = width
            out.append(line[:cut].rstrip())
            line = line[cut:].lstrip()
        out.append(line)
    return out


def _icon(kind):
    """32 x 32 icons of the dialogs, drawn here (NaN where the dialog shows
    through)."""
    n = 32
    y, x = np.mgrid[0:n, 0:n] + 0.5
    c = n / 2
    a = np.full((n, n, 3), np.nan)
    if kind == 'warn':
        inside = (y > 3) & (y < 29) & (np.abs(x - c) < (y - 3) * 0.55)
        a[inside] = (0.98, 0.78, 0.12)
        bar = (np.abs(x - c) < 1.6) & (y > 10) & (y < 21)
        dot = (x - c) ** 2 + (y - 25) ** 2 < 3.2
        a[bar | dot] = (0.1, 0.1, 0.1)
        return a
    disc = (x - c) ** 2 + (y - c) ** 2 < 14.5 ** 2
    if kind == 'error':
        a[disc] = (0.82, 0.16, 0.16)
        u, v = x - c, y - c
        cross = ((np.abs(u - v) < 2.2) | (np.abs(u + v) < 2.2)) & (np.abs(u) < 7.5) & (np.abs(v) < 7.5)
        a[cross & disc] = (1.0, 1.0, 1.0)
    else:
        a[disc] = (0.16, 0.42, 0.78)
        bar = (np.abs(x - c) < 1.8) & (y > 13) & (y < 25)
        dot = (x - c) ** 2 + (y - 8.5) ** 2 < 4.5
        a[bar | dot] = (1.0, 1.0, 1.0)
    return a


def _custom_icon(data, cmap):
    a = np.asarray(data)
    if a.ndim == 3:
        return a.astype(float) / 255.0 if a.dtype == np.uint8 else a.astype(float)
    m = np.asarray(cmap, float).reshape(-1, 3) if cmap is not None and numel(cmap) else None
    if m is None:
        g = a.astype(float)
        g = g / 255.0 if a.dtype == np.uint8 else g
        return np.repeat(g[:, :, None], 3, axis=2)
    idx = a.astype(int) if a.dtype.kind in 'iu' and a.dtype != np.uint8 else (a.astype(int) + (1 if a.dtype == np.uint8 else 0))
    idx = np.clip(idx - 1, 0, m.shape[0] - 1)
    return m[idx]


def _fit_icon(pic, n=32):
    """A picture stretched over the icon's square, as an image fills its axes."""
    h, w = pic.shape[:2]
    if (h, w) == (n, n) or not h or not w:
        return pic
    return pic[np.arange(n) * h // n][:, np.arange(n) * w // n]


def message_dialog(message, title, icon='none', icondata=None, cmap=None, modal=False):
    # a message made by sprintf holds its line breaks in one row
    lines = _wrap([part for ln in (lines_of(message) or ['']) for part in ln.split('\n')]) or ['']
    pic = _icon(icon) if icon in ('error', 'warn', 'help') else (_fit_icon(_custom_icon(icondata, cmap)) if icon == 'custom' and icondata is not None else None)
    tw = max(len(ln) for ln in lines) * 6.2 + 8
    th = len(lines) * 14.0 + 4
    iw = 42.0 if pic is not None else 0.0
    w = min(560.0, max(190.0, 12 + iw + tw + 12))
    body = max(th, 34.0 if pic is not None else 0.0)
    h = 12 + body + 12 + 24 + 10
    f = dialog_figure(title, w, h, modal)
    if pic is not None:
        ic = UIControl(f)
        ic.props.update(Style='text', String=Char.of(''), Position=np.array([[12.0, h - 12 - 32 - (body - 32) / 2, 32.0, 32.0]]),
                        CData=pic, Tag='IconAxes')
    t = UIControl(f)
    t.props.update(Style='text', String=Cell.of_list([Char.of(s) for s in lines], (len(lines), 1)), HorizontalAlignment='left',
                   Position=np.array([[12 + iw, h - 12 - body + (body - th) / 2, w - 24 - iw, th]]), Tag='MessageBox')
    ok = UIControl(f)
    ok.props.update(Style='pushbutton', String=Char.of('OK'), Position=np.array([[(w - 64) / 2, 10.0, 64.0, 24.0]]), Tag='OKButton',
                    Callback=lambda src, evt: f.delete_handle(), KeyPressFcn=lambda src, evt: f.delete_handle())
    f.touch()
    return f


def _createmode(args):
    for a in args:
        s = opt_str(a)
        if s is not None and s.lower() in ('modal', 'non-modal', 'replace'):
            return s.lower() == 'modal'
        if type(a) is Struct and 'WindowStyle' in a.f:
            return py_str(a.get1('WindowStyle')).lower() == 'modal'
    return False


@bi('msgbox', arr=False)
def msgbox(nargout, *args):
    msg = args[0] if args else Char.of('')
    title = py_str(args[1]) if len(args) > 1 and is_str(args[1]) else ''
    icon = opt_lower(args[2]) if len(args) > 2 and is_str(args[2]) and opt_lower(args[2]) in ('none', 'error', 'help', 'warn', 'custom') else 'none'
    data = args[3] if icon == 'custom' and len(args) > 3 else None
    cmap = args[4] if icon == 'custom' and len(args) > 4 and not is_str(args[4]) else None
    f = message_dialog(msg, title, icon, data, cmap, _createmode(args[2:]))
    return f if nargout else None


def _kind_dialog(kind, title0, args, nargout):
    msg = args[0] if args else Char.of('')
    title = py_str(args[1]) if len(args) > 1 and is_str(args[1]) else title0
    f = message_dialog(msg, title, kind, modal=_createmode(args[2:]))
    return f if nargout else None


@bi('errordlg', arr=False)
def errordlg(nargout, *args):
    return _kind_dialog('error', 'Error', args, nargout)


@bi('warndlg', arr=False)
def warndlg(nargout, *args):
    return _kind_dialog('warn', 'Warning', args, nargout)


@bi('helpdlg', arr=False)
def helpdlg(nargout, *args):
    return _kind_dialog('help', 'Help', args, nargout)


@bi('dialog', arr=False)
def dialog(nargout, *args):
    _, pairs = _pairs(args, 'dialog')
    f = dialog_figure('', 360, 160, modal=True)
    for k, v in pairs:
        f.setprop(k, v)
    f.touch()
    return f


# ---- waitbar ----------------------------------------------------------------------------------------------

def _bar_parts(f):
    ax = next((c for c in f.children if c.valid and c.TYPE == 'axes'), None)
    patch = next((c for c in ax.children if c.valid and c.TYPE == 'patch'), None) if ax is not None else None
    return ax, patch


def _set_bar(f, x, msg=None):
    ax, patch = _bar_parts(f)
    if ax is None or patch is None:
        return
    x = min(max(float(x), 0.0), 1.0) * 100
    patch.props['XData'] = np.array([[0.0], [x], [x], [0.0]])
    if msg is not None:
        ax.title.set_value('String', msg)
    ax.touch()


@bi('waitbar', arr=False)
def waitbar(nargout, *args):
    nargchk(args, 1, None, 'waitbar')
    x = float(num(args[0]))
    rest = list(args[1:])
    f = None
    if rest and not is_str(rest[0]) and type(rest[0]) is not Cell:
        f = _one(rest.pop(0))
        if not isinstance(f, Figure) or not f.valid:
            raise err('MATLAB:waitbar:InvalidInput', 'The second input must be the handle of a waitbar.', 'waitbar')
    elif not rest and _LAST_WAITBAR[0] is not None and _LAST_WAITBAR[0].valid:
        f = _LAST_WAITBAR[0]
    msg = rest.pop(0) if rest and (is_str(rest[0]) or type(rest[0]) is Cell) else None
    pairs = [(sval(rest[i], 'property name', 'waitbar'), rest[i + 1]) for i in range(0, len(rest) - 1, 2)]
    if f is not None:
        _set_bar(f, x, msg)
        for k, v in pairs:
            f.setprop(k, v)
        f.touch()
        return f if nargout else None
    cancel = next((v for k, v in pairs if k.lower() == 'createcancelbtn'), None)
    pairs = [(k, v) for k, v in pairs if k.lower() != 'createcancelbtn']
    w, h = 360.0, 82.0 + (30.0 if cancel is not None else 0.0)
    f = dialog_figure('', w, h)
    base = 12.0 + (30.0 if cancel is not None else 0.0)
    ax = Axes(f)
    ax.props.update(Units='pixels', Position=np.array([[12.0, base, w - 24, 16.0]]), XLim=np.array([[0.0, 100.0]]), XLimMode='manual',
                    YLim=np.array([[0.0, 1.0]]), YLimMode='manual', XTick=np.zeros((1, 0)), XTickMode='manual',
                    YTick=np.zeros((1, 0)), YTickMode='manual', Box=True, Layer='top')
    ax.title.props['FontWeight'] = 'normal'
    ax.title.props['FontSize'] = 9.0
    p = Patch(ax)
    p.props.update(XData=np.array([[0.0], [0.0], [0.0], [0.0]]), YData=np.array([[0.0], [0.0], [1.0], [1.0]]),
                   FaceColor=(0.0, 0.447, 0.741), EdgeColor=(0.0, 0.447, 0.741))
    if cancel is not None:
        b = UIControl(f)
        b.props.update(Style='pushbutton', String=Char.of('Cancel'), Position=np.array([[w - 82.0, 8.0, 70.0, 24.0]]), Tag='TMWWaitbarCancelButton')
        b.set_value('Callback', cancel)
        f.set_value('CloseRequestFcn', cancel)
    _set_bar(f, x, msg if msg is not None else Char.of(''))
    for k, v in pairs:
        f.setprop(k, v)
    f.touch()
    _LAST_WAITBAR[0] = f
    return f if nargout else None


# ---- dialogs the page shows ---------------------------------------------------------------------------------

def _texts(v):
    return lines_of(v) if v is not None else []


async def _ask(req):
    R.flush_figures()
    return await R.ask_page(req)


@bi('questdlg', aw=True, arr=False)
async def questdlg(nargout, *args):
    nargchk(args, 1, 6, 'questdlg')
    question = _texts(args[0])
    title = py_str(args[1]) if len(args) > 1 else ''
    rest = list(args[2:])
    opts = rest.pop() if rest and type(rest[-1]) is Struct else None
    words = [py_str(a) for a in rest]
    default = py_str(opts.get1('Default')) if opts is not None and 'Default' in opts.f else None
    if not words:
        buttons, default = ['Yes', 'No', 'Cancel'], default or 'Yes'
    elif len(words) == 1:
        buttons, default = ['Yes', 'No', 'Cancel'], words[0]
    else:
        buttons, default = words[:-1] if opts is None else words, (words[-1] if opts is None else default)
    ans = await _ask({'type': 'questdlg', 'question': question, 'title': title, 'buttons': buttons[:3], 'default': default})
    return Char.of(ans if isinstance(ans, str) else '')


@bi('inputdlg', aw=True, arr=False)
async def inputdlg(nargout, *args):
    prompts = _texts(args[0]) if args else ['']
    title = py_str(args[1]) if len(args) > 1 else ''
    dims = np.asarray(args[2], float).reshape(-1) if len(args) > 2 and numel(args[2]) else np.array([1.0])
    rows = [int(dims[0])] * len(prompts) if dims.size in (1, 2) and not (dims.size == len(prompts) and dims.size > 2) else [int(d) for d in dims[:len(prompts)]]
    if isinstance(args[2] if len(args) > 2 else None, np.ndarray) and args[2].ndim == 2 and args[2].shape[0] == len(prompts) and args[2].shape[0] > 1:
        rows = [int(r) for r in args[2][:, 0]]
    defaults = _texts(args[3]) if len(args) > 3 else [''] * len(prompts)
    defaults = (defaults + [''] * len(prompts))[:len(prompts)]
    ans = await _ask({'type': 'inputdlg', 'prompts': prompts, 'title': title, 'rows': rows, 'defaults': defaults})
    if not isinstance(ans, list):
        return Cell(np.empty((0, 0), object))
    return Cell.of_list([Char.of(str(s)) for s in ans], (len(ans), 1))


@bi('listdlg', aw=True, nout=2, arr=False)
async def listdlg(nargout, *args):
    opts = {}
    for i in range(0, len(args) - 1, 2):
        opts[sval(args[i], 'option name', 'listdlg').lower()] = args[i + 1]
    if 'liststring' not in opts:
        raise err('MATLAB:listdlg:NoListString', "listdlg needs a 'ListString'.", 'listdlg')
    items = _texts(opts['liststring'])
    single = py_str(opts['selectionmode']).lower() == 'single' if 'selectionmode' in opts else False
    init = [int(v) - 1 for v in np.asarray(opts['initialvalue'], float).reshape(-1)] if 'initialvalue' in opts else [0]
    ans = await _ask({'type': 'listdlg', 'items': items, 'multiple': not single, 'initial': init,
                      'prompt': _texts(opts.get('promptstring')), 'title': py_str(opts['name']) if 'name' in opts else '',
                      'ok': py_str(opts['okstring']) if 'okstring' in opts else 'OK',
                      'cancel': py_str(opts['cancelstring']) if 'cancelstring' in opts else 'Cancel'})
    if not isinstance(ans, list):
        res = (np.zeros((0, 0)), 0.0)
    else:
        res = (np.array([[float(i) + 1 for i in ans]]) if ans else np.zeros((1, 0)), 1.0)
    return res if nargout > 1 else res[0]


def _filters(spec):
    """A file filter as [[patterns, description]] and the folder it names."""
    folder = None
    if spec is None or (is_str(spec) and not py_str(spec).strip()):
        return [['*.*', 'All files (*.*)']], folder
    if is_str(spec):
        s = py_str(spec)
        if '/' in s:
            folder, s = os.path.split(s)
        if not s or '*' not in s:
            return [['*.*', 'All files (*.*)']], folder
        return [[s, s]], folder
    if type(spec) is Cell:
        a = spec.a
        if a.ndim == 2 and a.shape[1] >= 2:
            return [[py_str(a[i, 0]), py_str(a[i, 1])] for i in range(a.shape[0])], folder
        pats = [py_str(x) for x in a.reshape(-1, order='F')]
        return [[p, p] for p in pats], folder
    raise err('MATLAB:uigetfile:InvalidFilter', 'A file filter is text or a cell array of patterns.', 'uigetfile')


async def _pick(mode, args, fn):
    flt, folder = _filters(args[0] if args else None)
    title = py_str(args[1]) if len(args) > 1 and is_str(args[1]) else ('Select a file' if mode == 'open' else 'Save as')
    name = ''
    multi = False
    i = 2
    while i < len(args):
        s = opt_str(args[i])
        if s is not None and s.lower() == 'multiselect' and i + 1 < len(args):
            multi = py_str(args[i + 1]).lower() == 'on'
            i += 2
            continue
        if s is not None and i == 2:
            name = s
        i += 1
    if name and '/' in name:
        folder, name = os.path.split(name)
    from .iofun import abspath
    start = abspath(folder) if folder else R.STATE['cwd']
    if not os.path.isdir(start):
        start = R.STATE['cwd']
    ans = await _ask({'type': 'pickfile', 'mode': mode, 'filters': flt, 'title': title, 'start': start, 'name': name, 'multi': multi})
    return ans if isinstance(ans, dict) else None


@bi('uigetfile', aw=True, nout=3, arr=False)
async def uigetfile(nargout, *args):
    ans = await _pick('open', args, 'uigetfile')
    if ans is None or not ans.get('names'):
        return (0.0, 0.0, 0.0)[:max(1, nargout)] if nargout > 1 else 0.0
    names = ans['names']
    file = Char.of(names[0]) if len(names) == 1 else Cell.of_list([Char.of(n) for n in names])
    path = Char.of(ans['path'].rstrip('/') + '/')
    res = (file, path, float(ans.get('filter', 0)) + 1)
    return res[:nargout] if nargout > 1 else file


@bi('uiputfile', aw=True, nout=3, arr=False)
async def uiputfile(nargout, *args):
    ans = await _pick('save', args, 'uiputfile')
    if ans is None or not ans.get('names'):
        return (0.0, 0.0, 0.0)[:max(1, nargout)] if nargout > 1 else 0.0
    res = (Char.of(ans['names'][0]), Char.of(ans['path'].rstrip('/') + '/'), float(ans.get('filter', 0)) + 1)
    return res[:nargout] if nargout > 1 else res[0]


@bi('uigetdir', aw=True, arr=False)
async def uigetdir(nargout, *args):
    from .iofun import abspath
    start = abspath(py_str(args[0])) if args and is_str(args[0]) and py_str(args[0]) else R.STATE['cwd']
    if not os.path.isdir(start):
        start = R.STATE['cwd']
    title = py_str(args[1]) if len(args) > 1 else 'Select a folder'
    ans = await _ask({'type': 'pickfile', 'mode': 'dir', 'filters': [], 'title': title, 'start': start, 'name': '', 'multi': False})
    if not isinstance(ans, dict) or not ans.get('path'):
        return 0.0
    return Char.of(ans['path'])


@bi('uisetcolor', aw=True, arr=False)
async def uisetcolor(nargout, *args):
    rgb = None
    title = 'Color'
    for a in args:
        if is_str(a):
            title = py_str(a)
        elif isinstance(a, GObj):
            c = a.props.get('Color', a.props.get('BackgroundColor'))
            rgb = list(c) if isinstance(c, tuple) else None
        elif numel(a) == 3:
            rgb = [float(x) for x in np.asarray(a, float).reshape(-1)]
    ans = await _ask({'type': 'color', 'value': rgb or [1.0, 1.0, 1.0], 'title': title})
    if not isinstance(ans, list) or len(ans) != 3:
        return np.array([rgb]) if rgb is not None else 0.0
    return np.array([[float(x) for x in ans]])


@bi('menu', aw=True, arr=False)
async def menu(nargout, *args):
    nargchk(args, 2, None, 'menu')
    items = [py_str(a) for a in args[1:]] if not (len(args) == 2 and type(args[1]) is Cell) else cellstr_list(args[1])
    ans = await _ask({'type': 'menu', 'title': py_str(args[0]), 'items': items})
    return float(ans) + 1 if isinstance(ans, (int, float)) and ans >= 0 else 0.0


@bi('printdlg', 'printpreview', aw=True, arr=False)
async def printdlg(nargout, *args):
    h = _one(args[0]) if args and not is_str(args[0]) else gcf_()
    f = h.figure() if isinstance(h, GObj) else gcf_()
    await _ask({'type': 'print', 'figure': f.id})
    return None


# ---- timers ------------------------------------------------------------------------------------------------

def _timers(v, fn):
    if isinstance(v, E.Timer):
        return [v]
    if isinstance(v, HArr):
        ts = [t for t in v.a.reshape(-1) if isinstance(t, E.Timer)]
        if len(ts) == v.a.size:
            return ts
    raise err('MATLAB:timer:invalid', f'{fn} needs timer objects.', fn)


@bi('timer', arr=False)
def timer(nargout, *args):
    if len(args) % 2:
        raise err('MATLAB:timer:pvpairs', 'Invalid parameter/value pair arguments.', 'timer')
    t = E.Timer()
    try:
        for i in range(0, len(args), 2):
            t.setprop(sval(args[i], 'property name', 'timer'), args[i + 1])
    except MError:
        t.remove()
        raise
    return t


@bi('start', aw=True, arr=False)
async def start(nargout, *args):
    nargchk(args, 1, 1, 'start')
    for t in _timers(args[0], 'start'):
        if not t.valid:
            raise err('MATLAB:timer:invalid', 'Invalid or deleted timer.', 'start')
        if t.running:
            raise err('MATLAB:timer:alreadyrunning', f"Timer '{t.props['Name']}' is already running.", 'start')
        await E.run_one(t, 'StartFcn', t._event('StartFcn'))
        t.start()
    return None


@bi('stop', aw=True, arr=False)
async def stop(nargout, *args):
    nargchk(args, 1, 1, 'stop')
    for t in _timers(args[0], 'stop'):
        if t.valid and t.halt():
            await E.run_one(t, 'StopFcn', t._event('StopFcn'))
    return None


@bi('wait', aw=True, arr=False)
async def wait(nargout, *args):
    nargchk(args, 1, 1, 'wait')
    ts = _timers(args[0], 'wait')
    await E.wait_until(lambda: not any(t.valid and t.running for t in ts))
    return None


def _find_timers(args, all_):
    ts = [t for t in E.TIMERS.values() if t.valid and (all_ or t.props['ObjectVisibility'] == 'on')]
    for i in range(0, len(args) - 1, 2):
        k = sval(args[i], 'property name', 'timerfind')
        from .core import _equal
        ts = [t for t in ts if t.canon(k) is not None and _equal(t.getprop(k), args[i + 1], False)]
    return HArr.of(ts, col=True) if ts else EMPTY()


@bi('timerfind', arr=False)
def timerfind(nargout, *args):
    return _find_timers(args, False)


@bi('timerfindall', arr=False)
def timerfindall(nargout, *args):
    return _find_timers(args, True)


# ---- sound ---------------------------------------------------------------------------------------------------

BEEP = [True]


def _audio(y, fn):
    """Samples as a column per channel: a vector is one channel."""
    a = darr(y)
    if a.ndim == 2 and 1 in a.shape:
        a = a.reshape(-1, 1)
    if a.ndim != 2 or a.shape[1] > 2:
        raise err(f'MATLAB:{fn}:invalidChannels', 'Audio data must be a vector, or a matrix of two columns (left and right).', fn)
    return a


def _rate(args, fn):
    fs = float(num(args[0])) if args else 8192.0
    if not (math.isfinite(fs) and fs > 0):
        raise err(f'MATLAB:{fn}:invalidRate', 'The sample rate must be a positive number of samples a second.', fn)
    return fs


def _play(a, fs):
    """The samples to the page, which plays them through its audio at once."""
    hook = R.EVENT_HOOK[0]
    if hook is None or not a.size:
        return
    data = np.ascontiguousarray(np.nan_to_num(a).T, '<f4').tobytes()
    hook({'type': 'sound', 'rate': fs, 'channels': int(a.shape[1]), 'data': base64.b64encode(data).decode('ascii')})


@bi('sound', arr=False)
def sound(nargout, *args):
    nargchk(args, 1, 3, 'sound')
    a = _audio(args[0], 'sound')
    _play(np.clip(a, -1.0, 1.0), _rate(args[1:2], 'sound'))
    return None


@bi('soundsc', arr=False)
def soundsc(nargout, *args):
    nargchk(args, 1, 4, 'soundsc')
    a = _audio(args[0], 'soundsc')
    rest = list(args[1:])
    if rest and numel(rest[-1]) == 2:
        lo, hi = (float(x) for x in darr(rest.pop()).reshape(-1))
    else:
        finite = a[np.isfinite(a)]
        lo, hi = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 0.0)
    # the range given (or the data's own) fills -1 to 1
    y = (a - lo) / (hi - lo) * 2.0 - 1.0 if hi > lo else np.zeros_like(a)
    _play(np.clip(y, -1.0, 1.0), _rate(rest[:1], 'soundsc'))
    return None


@bi('beep', arr=False)
def beep(nargout, *args):
    if args:
        s = sval(args[0], 'option', 'beep').lower()
        if s not in ('on', 'off'):
            raise err('MATLAB:beep:badOption', 'Use beep on or beep off.', 'beep')
        BEEP[0] = s == 'on'
        return None
    if nargout:
        return Char.of('on' if BEEP[0] else 'off')
    if BEEP[0]:
        n = int(0.12 * 8192)
        y = 0.4 * np.sin(2 * np.pi * 880.0 * np.arange(n) / 8192.0) * np.minimum(1.0, (n - np.arange(n)) / 200.0)
        _play(y.reshape(-1, 1), 8192.0)
    return None


# ---- icons for programs that load MATLAB's ------------------------------------------------------------------

def _glyph(rows, ink, fill=None):
    """A 16 x 16 icon from text: '#' is ink, 'o' fill, '.' clear."""
    a = np.full((16, 16, 3), np.nan)
    for i, row in enumerate(rows):
        for j, ch in enumerate(row[:16]):
            if ch == '#':
                a[i, j] = ink
            elif ch == 'o' and fill is not None:
                a[i, j] = fill
    return a


_PAGE = ['...#######......', '...#ooooo##.....', '...#ooooo#o#....', '...#ooooo####...', '...#oooooooo#...',
         '...#oooooooo#...', '...#oooooooo#...', '...#oooooooo#...', '...#oooooooo#...', '...#oooooooo#...',
         '...#oooooooo#...', '...#oooooooo#...', '...#oooooooo#...', '...##########...', '................', '................']
_FOLDER = ['................', '................', '.####...........', '#oooo#..........', '#ooooo########..', '#oooooooooooo#..',
           '#oooooooooooo#..', '#oooooooooooo#..', '#oooooooooooo#..', '#oooooooooooo#..', '#oooooooooooo#..', '#oooooooooooo#..',
           '##############..', '................', '................', '................']
_DISK = ['................', '.#############..', '.#o#######o#o#..', '.#o#######o#o#..', '.#o#######ooo#..', '.#ooooooooooo#..',
         '.#ooooooooooo#..', '.#o#########o#..', '.#o#ooooooo#o#..', '.#o#ooooooo#o#..', '.#o#ooooooo#o#..', '.#o#ooooooo#o#..',
         '.#############..', '................', '................', '................']
_PRINTER = ['................', '....########....', '....#oooooo#....', '....#oooooo#....', '..############..', '.#oooooooooooo#.',
            '.#oooooooooo##..', '.#oooooooooooo#.', '.##############.', '...#oooooooo#...', '...#oooooooo#...', '...##########...',
            '................', '................', '................', '................']

ICONS = {'newdoc': (_PAGE, (0.2, 0.2, 0.25), (1.0, 1.0, 1.0)), 'opendoc': (_FOLDER, (0.45, 0.33, 0.1), (0.95, 0.8, 0.4)),
         'savedoc': (_DISK, (0.1, 0.2, 0.45), (0.55, 0.7, 0.95)), 'printdoc': (_PRINTER, (0.2, 0.2, 0.25), (0.9, 0.9, 0.9))}


def write_icons(root='/pylab'):
    """toolbox/matlab/icons under matlabroot: programs made for MATLAB load
    their toolbar pictures from there. These are drawn here, in pylab's
    own hand; only the names are the same."""
    folder = os.path.join(root, 'toolbox', 'matlab', 'icons')
    try:
        os.makedirs(folder, exist_ok=True)
        import scipy.io as sio
        for name, (rows, ink, fill) in ICONS.items():
            sio.savemat(os.path.join(folder, name + '.mat'), {'cdata': _glyph(rows, ink, fill)})
    except Exception:
        pass
