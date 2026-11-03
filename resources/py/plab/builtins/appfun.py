"""The functions that make apps' windows and components: uifigure, uibutton
and the other components of uiapp.py, uigridlayout, uiaxes, and the
dialogs of apps (uialert, uiconfirm, uiprogressdlg). Panels, tab groups,
button groups and tables made in an app's window take pixels, as there.
"""
import itertools

import numpy as np

from . import bi, REG
from ._util import err, opt_str, is_str, sval, num
from ..values import MError, Char, Cell, Struct, FH, Obj, EMPTY, numel, py_str
from ..graphics_base import Figure, Axes, ROOT, register, HArr
from .. import uiapp as A
from .. import uievents as E
from .. import runtime as R
from .uifun import _pairs, _one, message_dialog

_numbers = itertools.count(1001)


class UIFigure(Figure):
    """uifigure: an app's window: no number, a hidden handle, no menus or tools."""
    DEFAULTS = {**Figure.DEFAULTS, 'AutoResizeChildren': True, 'Scrollable': False, 'Icon': '', 'WindowState': 'normal', 'Theme': None}


register(UIFigure)
for _C in (Axes,):
    _C.DEFAULTS.setdefault('Layout', None)
from ..uiobjects import UIPanel, UIButtonGroup, UITabGroup, UITable, UIControl  # noqa: E402
for _C in (UIPanel, UIButtonGroup, UITabGroup, UITable, UIControl):
    _C.DEFAULTS.setdefault('Layout', None)
for _C in (UIPanel, UIButtonGroup):
    _C.DEFAULTS.setdefault('Scrollable', False)
    _C.DEFAULTS.setdefault('AutoResizeChildren', True)
register(Axes, UIPanel, UIButtonGroup, UITabGroup, UITable, UIControl)

_HOLDERS = ('figure', 'uipanel', 'uibuttongroup', 'uitab', 'uigridlayout')


@bi('uifigure', arr=False)
def uifigure(nargout, *args):
    _, pairs = _pairs(args, 'uifigure')
    f = UIFigure(-next(_numbers))
    scr = np.asarray(ROOT.props['ScreenSize'], float).reshape(-1)
    f.props.update(Name='UI Figure', MenuBar='none', ToolBar='none', HandleVisibility='off', NumberTitle=False,
                   Position=np.array([[100.0, max(40.0, scr[3] - 580.0), 640.0, 480.0]]))
    for k, v in pairs:
        f.setprop(k, v)
    f.touch()
    E.created(f)
    return f


def _parent_and_style(args, styles, fn):
    """(parent, style, name-value pairs) of uiX(parent, style, Name, Value, ...); a new uifigure when no parent is given."""
    rest = list(args)
    parent = None
    if rest and not is_str(rest[0]) and type(rest[0]) is not Struct:
        parent = _one(rest.pop(0))
    style = None
    if rest and len(rest) % 2 == 1 and opt_str(rest[0]) is not None and opt_str(rest[0]).lower() in styles:
        style = opt_str(rest.pop(0)).lower()
    if len(rest) % 2:
        raise err('MATLAB:ui:NameValuePairs', 'Properties must come in name-value pairs.', fn)
    pairs = [(sval(rest[i], 'property name', fn), rest[i + 1]) for i in range(0, len(rest), 2)]
    for k, v in pairs:
        if k.lower() == 'parent':
            parent = _one(v)
    pairs = [(k, v) for k, v in pairs if k.lower() != 'parent']
    if parent is None:
        parent = uifigure(1)
    return parent, style, pairs


def _make(kind, parent, pairs, fn):
    if getattr(parent, 'TYPE', None) not in _HOLDERS or not parent.valid:
        raise err('MATLAB:ui:InvalidParent', f'The parent of a component must be a uifigure, a panel, a tab, a button group or a grid layout.', fn)
    if kind in ('radiobutton', 'togglebutton') and parent.TYPE != 'uibuttongroup':
        raise err('MATLAB:ui:InvalidParent', f'A {A.KINDS[kind][0]} goes in a button group (uibuttongroup).', fn)
    h = A.CLASSES[kind](parent)
    if kind in ('radiobutton', 'togglebutton') and parent.TYPE == 'uibuttongroup' and parent.selection() is None:
        h.props['Value'] = True
    try:
        for k, v in pairs:
            h.setprop(k, v)
    except MError:
        h.delete_handle()
        raise
    h.touch()
    E.created(h)
    return h


def _maker(name, kinds, default):
    """uiX(parent, style, ...): kinds maps the styles to the component kinds."""
    def f(nargout, *args):
        parent, style, pairs = _parent_and_style(args, kinds, name)
        kind = kinds.get(style, default) if style else default
        if name == 'uiswitch':
            h = _make(kind, parent, [], name)
            h.props['Style'] = style or 'slider'
            if style in ('rocker', 'toggle'):
                h.props['Position'] = np.array([[100.0, 100.0, 20.0, 45.0]])
                h.props['Orientation'] = 'vertical'
            for k, v in pairs:
                h.setprop(k, v)
            return h
        if name == 'uigauge':
            h = _make(kind, parent, [], name)
            h.props['Style'] = style or 'circular'
            if style == 'linear':
                h.props['Position'] = np.array([[100.0, 100.0, 120.0, 40.0]])
            elif style == 'semicircular':
                h.props['Position'] = np.array([[100.0, 100.0, 120.0, 65.0]])
            elif style == 'ninetydegree':
                h.props['Position'] = np.array([[100.0, 100.0, 90.0, 90.0]])
            for k, v in pairs:
                h.setprop(k, v)
            return h
        return _make(kind, parent, pairs, name)
    f.__name__ = name
    return f


for _name, _kinds, _default in (
        ('uibutton', {'push': 'button', 'state': 'statebutton'}, 'button'),
        ('uilabel', {}, 'label'),
        ('uieditfield', {'text': 'editfield', 'numeric': 'numericeditfield'}, 'editfield'),
        ('uitextarea', {}, 'textarea'),
        ('uidropdown', {}, 'dropdown'),
        ('uilistbox', {}, 'listbox'),
        ('uicheckbox', {}, 'checkbox'),
        ('uiswitch', {'slider': 'switch', 'rocker': 'switch', 'toggle': 'switch'}, 'switch'),
        ('uislider', {}, 'slider'),
        ('uispinner', {}, 'spinner'),
        ('uiknob', {'continuous': 'knob', 'discrete': 'discreteknob'}, 'knob'),
        ('uigauge', {'circular': 'gauge', 'linear': 'gauge', 'ninetydegree': 'gauge', 'semicircular': 'gauge'}, 'gauge'),
        ('uilamp', {}, 'lamp'),
        ('uiradiobutton', {}, 'radiobutton'),
        ('uitogglebutton', {}, 'togglebutton'),
        ('uiimage', {}, 'image'),
        ('uihyperlink', {}, 'hyperlink')):
    bi(_name, arr=False)(_maker(_name, _kinds, _default))


@bi('uigridlayout', arr=False)
def uigridlayout(nargout, *args):
    rest = list(args)
    parent = _one(rest.pop(0)) if rest and not is_str(rest[0]) else None
    size = None
    if rest and not is_str(rest[0]):
        size = [int(x) for x in np.asarray(rest.pop(0), float).reshape(-1)]
    if len(rest) % 2:
        raise err('MATLAB:ui:NameValuePairs', 'Properties must come in name-value pairs.', 'uigridlayout')
    pairs = [(sval(rest[i], 'property name', 'uigridlayout'), rest[i + 1]) for i in range(0, len(rest), 2)]
    parent = next((_one(v) for k, v in pairs if k.lower() == 'parent'), parent)
    pairs = [(k, v) for k, v in pairs if k.lower() != 'parent']
    if parent is None:
        parent = uifigure(1)
    if getattr(parent, 'TYPE', None) not in _HOLDERS:
        raise err('MATLAB:ui:InvalidParent', 'The parent of a grid layout must be a uifigure, a panel, a tab or a grid layout.', 'uigridlayout')
    g = A.UIGridLayout(parent)
    if size:
        r, c = (size + [size[0]])[:2] if len(size) == 1 else size[:2]
        g.props['RowHeight'] = A._cells(['1x'] * r)
        g.props['ColumnWidth'] = A._cells(['1x'] * c)
    for k, v in pairs:
        g.setprop(k, v)
    g.touch()
    E.created(g)
    return g


@bi('uiaxes', arr=False)
def uiaxes(nargout, *args):
    rest = list(args)
    parent = _one(rest.pop(0)) if rest and not is_str(rest[0]) else None
    pairs = [(sval(rest[i], 'property name', 'uiaxes'), rest[i + 1]) for i in range(0, len(rest) - 1, 2)]
    parent = next((_one(v) for k, v in pairs if k.lower() == 'parent'), parent)
    pairs = [(k, v) for k, v in pairs if k.lower() != 'parent']
    if parent is None:
        parent = uifigure(1)
    ax = Axes(parent)
    ax.props['Units'] = 'pixels'
    ax.props['Position'] = np.array([[55.0, 45.0, 300.0, 200.0]])
    ax.props['Box'] = True
    ax.props['HandleVisibility'] = 'on'
    for k, v in pairs:
        ax.setprop(k, v)
    ax.touch()
    return ax


# panels and their kin in an app's window take pixels
def _in_app(h):
    f = h.figure() if hasattr(h, 'figure') else None
    return isinstance(f, UIFigure)


def _pixel_default(name, pos):
    info = REG[name]
    orig = info.fn

    def f(nargout, *args):
        h = orig(1, *args)
        given = {str(a).lower() for a in args if is_str(a)}
        if _in_app(h) and 'units' not in {py_str(a).lower() for a in args if is_str(a)}:
            if 'position' not in {py_str(a).lower() for a in args if is_str(a)}:
                h.props['Position'] = np.array([pos], float)
            h.props['Units'] = 'pixels'
            h.touch()
        return h if nargout else None
    info.fn = f


for _n, _pos in (('uipanel', [20.0, 20.0, 260.0, 221.0]), ('uibuttongroup', [20.0, 20.0, 123.0, 106.0]),
                 ('uitabgroup', [20.0, 20.0, 302.0, 221.0]), ('uitable', [20.0, 20.0, 302.0, 185.0])):
    if _n in REG:
        _pixel_default(_n, _pos)


# ---- the dialogs of apps -------------------------------------------------------------------------------------------

@bi('uialert', arr=False)
def uialert(nargout, *args):
    if len(args) < 3:
        raise err('MATLAB:minrhs', 'uialert takes the window, the message and the title.', 'uialert')
    names = {sval(args[i], 'option', 'uialert').lower(): args[i + 1] for i in range(3, len(args) - 1, 2)}
    icon = py_str(names.get('icon', Char.of('error'))).lower()
    icon = {'error': 'error', 'warning': 'warn', 'info': 'help', 'success': 'help', 'none': 'none'}.get(icon, 'error')
    message_dialog(args[1], py_str(args[2]), icon, None, None, 'modal' if bool(np.all(np.asarray(names.get('Modal'.lower(), True)))) else 'non-modal')
    return None


@bi('uiconfirm', aw=True, arr=False)
async def uiconfirm(nargout, *args):
    if len(args) < 3:
        raise err('MATLAB:minrhs', 'uiconfirm takes the window, the message and the title.', 'uiconfirm')
    names = {sval(args[i], 'option', 'uiconfirm').lower(): args[i + 1] for i in range(3, len(args) - 1, 2)}
    opts = [py_str(x) for x in names['options'].a.reshape(-1, order='F')] if 'options' in names else ['OK', 'Cancel']
    default = names.get('defaultoption')
    if default is not None and not is_str(default):
        default = opts[int(num(default)) - 1]
    default = py_str(default) if default is not None else opts[0]
    from .uifun import _ask, _texts
    ans = await _ask({'type': 'questdlg', 'question': _texts(args[1]), 'title': py_str(args[2]), 'buttons': opts[:3], 'default': default})
    cancel = names.get('canceloption')
    if not isinstance(ans, str) or not ans:
        ans = py_str(cancel) if cancel is not None and is_str(cancel) else opts[-1]
    if 'closefcn' in names:
        await E.call(names['closefcn'], args[0], Struct.scalar({'SelectedOption': Char.of(ans), 'Source': args[0], 'EventName': Char.of('ConfirmDialogClosed')}))
    return Char.of(ans)


class ProgressDlg(Obj):
    """uiprogressdlg: a bar with a message, its Value set by the program."""
    __slots__ = ('fig', 'props', 'open')
    is_handle = True
    cls = 'matlab.ui.dialog.ProgressDialog'

    def __init__(self, fig, props):
        self.fig = fig
        self.props = props
        self.open = True

    def _show(self):
        from .uifun import waitbar as wb
        if self.fig is None or not self.fig.valid:
            self.fig = wb(1, float(self.props['Value']), Char.of(self.props['Message']))
            self.fig.props['Name'] = self.props['Title']
        else:
            wb(0, float(self.props['Value']), self.fig, Char.of(self.props['Message']))

    def getprop(self, name):
        for k, v in self.props.items():
            if k.lower() == name.lower():
                return Char.of(v) if isinstance(v, str) else v
        return super().getprop(name)

    def setprop(self, name, value):
        for k in self.props:
            if k.lower() == name.lower():
                self.props[k] = py_str(value) if isinstance(self.props[k], str) else (bool(np.all(np.asarray(value))) if isinstance(self.props[k], bool) else float(num(value)))
                if self.open:
                    self._show()
                return
        super().setprop(name, value)

    def propnames(self):
        return list(self.props)

    def delete_handle(self):
        self.open = False
        if self.fig is not None and self.fig.valid:
            self.fig.delete_handle()


@bi('uiprogressdlg', arr=False)
def uiprogressdlg(nargout, *args):
    props = {'Value': 0.0, 'Message': '', 'Title': '', 'Indeterminate': False, 'Cancelable': False, 'CancelRequested': False, 'ShowPercentage': False}
    for i in range(1, len(args) - 1, 2):
        k = sval(args[i], 'option', 'uiprogressdlg')
        for kk in props:
            if kk.lower() == k.lower():
                v = args[i + 1]
                props[kk] = py_str(v) if isinstance(props[kk], str) else (bool(np.all(np.asarray(v))) if isinstance(props[kk], bool) else float(num(v)))
    d = ProgressDlg(None, props)
    d._show()
    return d


_orig_close = REG['close'].fn


async def _close(nargout, *args):
    if args and isinstance(args[0], ProgressDlg):
        args[0].delete_handle()
        return None
    return await _orig_close(nargout, *args)


REG['close'].fn = _close
