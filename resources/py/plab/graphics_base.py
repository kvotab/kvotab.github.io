"""Graphics objects: figures, axes and what is drawn in them, as handles
with properties (get/set and h.Prop). The page draws them from the
description serialize() makes; this side keeps the state that programs
query and change.
"""
import base64
import itertools
import math
import re

import numpy as np

from .values import (MError, NOVAL, Char, Cell, Struct, Str, FH, Obj, F64, C128, class_of, shape_of, numel,
                     _2d, EMPTY, py_str, share, size_str)

_ids = itertools.count(1)
DELETE_HOOK = [None]      # fn(obj): runs an object's DeleteFcn (set by uievents)


def gerr(msg, ident='MATLAB:graphics'):
    return MError(ident, msg)


# ---- colors -----------------------------------------------------------------------------

NAMED = {
    'r': (1, 0, 0), 'red': (1, 0, 0), 'g': (0, 1, 0), 'green': (0, 1, 0), 'b': (0, 0, 1), 'blue': (0, 0, 1),
    'c': (0, 1, 1), 'cyan': (0, 1, 1), 'm': (1, 0, 1), 'magenta': (1, 0, 1), 'y': (1, 1, 0), 'yellow': (1, 1, 0),
    'k': (0, 0, 0), 'black': (0, 0, 0), 'w': (1, 1, 1), 'white': (1, 1, 1),
}

COLOR_ORDER = np.array([[0, 0.447, 0.741], [0.85, 0.325, 0.098], [0.929, 0.694, 0.125], [0.494, 0.184, 0.556],
                        [0.466, 0.674, 0.188], [0.301, 0.745, 0.933], [0.635, 0.078, 0.184]])

AXIS_COLOR = (0.15, 0.15, 0.15)

# what every object a person can click has: callbacks, whether clicks reach
# it, and who sees its handle
INTERACT = {'ButtonDownFcn': '', 'UIContextMenu': None, 'HitTest': True, 'PickableParts': 'visible', 'Interruptible': True,
            'BusyAction': 'queue', 'CreateFcn': '', 'DeleteFcn': '', 'HandleVisibility': 'on', 'BeingDeleted': False,
            'Selected': False, 'SelectionHighlight': True}


def to_color(v, allowed=()):
    """A color value: an RGB triple (floats 0..1) or one of the allowed
    words ('none', 'flat', 'interp', 'auto')."""
    if v is None:
        return None
    t = type(v)
    if t in (Char, Str):
        s = py_str(v).strip()
        sl = s.lower()
        if sl in allowed:
            return sl
        if sl in NAMED:
            return tuple(float(x) for x in NAMED[sl])
        if sl.startswith('#') and len(sl) in (4, 7):
            h = sl[1:]
            if len(h) == 3:
                h = ''.join(c * 2 for c in h)
            return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        raise gerr(f"Invalid color name or hex code '{s}'.", 'MATLAB:hg:ColorSpec_None')
    a = np.asarray(v.a if t is Char else v, dtype=float) if t is not float else np.array([v])
    if a.size == 3:
        c = tuple(float(x) for x in a.reshape(-1))
        if any(x < 0 or x > 1 for x in c):
            raise gerr('Color value must be a 3 element vector with values between 0 and 1.', 'MATLAB:hg:ColorSpec_InvalidRGB')
        return c
    raise gerr('Color value must be a 3 element numeric vector, a color name or a hex code.', 'MATLAB:hg:ColorSpec_None')


def color_value(c):
    """A stored color as the language shows it."""
    if c is None:
        return Char.of('none')
    if isinstance(c, str):
        return Char.of(c)
    return np.array([list(c)], F64)


# ---- line specs ---------------------------------------------------------------------------

LINESTYLES = ('--', '-.', '-', ':')
MARKERS = {'o': 'o', '+': '+', '*': '*', '.': '.', 'x': 'x', 's': 's', 'd': 'd', '^': '^', 'v': 'v',
           '>': '>', '<': '<', 'p': 'p', 'h': 'h', '_': '_', '|': '|'}
MARKER_WORDS = {'circle': 'o', 'square': 's', 'diamond': 'd', 'pentagram': 'p', 'hexagram': 'h', 'none': 'none',
                'plus': '+', 'asterisk': '*', 'point': '.', 'cross': 'x', 'x': 'x', 'o': 'o', 's': 's', 'd': 'd',
                '^': '^', 'v': 'v', '>': '>', '<': '<', 'p': 'p', 'h': 'h', '+': '+', '*': '*', '.': '.'}


def parse_linespec(s):
    """'r--o' -> (color, linestyle, marker) or None when s is not a spec."""
    color = style = marker = None
    i = 0
    while i < len(s):
        two = s[i:i + 2]
        if two in ('--', '-.'):
            if style:
                return None
            style = two
            i += 2
            continue
        c = s[i]
        if c in '-:':
            if style:
                return None
            style = c
        elif c in 'rgbcmykw':
            if color:
                return None
            color = tuple(float(x) for x in NAMED[c])
        elif c in MARKERS:
            if marker:
                return None
            marker = c
        else:
            return None
        i += 1
    return color, style, marker


# ---- objects ---------------------------------------------------------------------------------

class GObj(Obj):
    """A graphics object. Properties live in a dict by their canonical
    names; get and set match names without regard to case."""
    TYPE = 'object'
    DEFAULTS = {}
    is_handle = True
    is_graphics = True
    CLASSNAME = 'matlab.graphics.Graphics'

    def __init__(self, parent=None, **props):
        self.id = next(_ids)
        self.props = {}
        for k, v in self.DEFAULTS.items():
            self.props[k] = v() if callable(v) and not isinstance(v, FH) else v
        self.parent = parent
        self.children = []
        self.valid = True
        if parent is not None:
            parent.children.insert(0, self)
        for k, v in props.items():
            self.props[k] = v
        STORE.objects[self.id] = self
        if USER_DEFAULTS[0]:
            self.apply_defaults()

    @property
    def cls(self):
        return self.CLASSNAME

    @classmethod
    def canon(cls, name):
        low = name.lower()
        m = cls._lower.get(low) or cls._alias.get(low)
        if m is None:
            # unique prefix matches too, as the language allows
            hits = [v for k, v in cls._lower.items() if k.startswith(low)]
            if len(hits) == 1:
                return hits[0]
            return None
        return m

    def figure(self):
        o = self
        while o is not None and o.TYPE != 'figure':
            o = o.parent
        return o

    def touch(self):
        f = self.figure()
        if f is not None:
            f.version += 1
            STORE.dirty.add(f)

    def getprop(self, name):
        if not self.valid:
            raise gerr('Invalid or deleted object.', 'MATLAB:class:InvalidHandle')
        if name == 'Parent':
            return self.parent if self.parent is not None else EMPTY()
        if name == 'Children':
            return HArr.of([c for c in self.children if c.valid and not getattr(c, 'hidden', False)], col=True)
        if name == 'Type':
            return Char.of(self.TYPE)
        k = self.canon(name)
        if k is None:
            if name.lower() == 'parent':
                return self.getprop('Parent')
            if name.lower() == 'children':
                return self.getprop('Children')
            if name.lower() == 'type':
                return Char.of(self.TYPE)
            d = split_default(name)
            if d is not None:
                return self.default_value(*d)
            raise gerr(f"Unrecognized property '{name}' for class '{self.CLASSNAME.split('.')[-1]}'.", 'MATLAB:noSuchMethodOrField')
        return self.get_value(k)

    def get_value(self, k):
        v = self.props.get(k)
        return export_value(k, v)

    def setprop(self, name, value):
        if not self.valid:
            raise gerr('Invalid or deleted object.', 'MATLAB:class:InvalidHandle')
        if name.lower() == 'parent':
            self.reparent(value)
            return
        k = self.canon(name)
        if k is None:
            d = split_default(name)
            if d is not None and d[0] == 'default':
                self.set_default(d[1], d[2], value)
                return
            raise gerr(f"Unrecognized property '{name}' for class '{self.CLASSNAME.split('.')[-1]}'.", 'MATLAB:noPublicFieldForClass')
        self.set_value(k, value)
        self.touch()

    def set_value(self, k, value):
        if k == 'FontUnits':
            from .uiobjects import set_font_units
            set_font_units(self, value)
            return
        self.props[k] = import_value(self, k, value)

    def reparent(self, p):
        if self.parent is not None and self in self.parent.children:
            self.parent.children.remove(self)
        self.parent = p
        p.children.insert(0, self)
        self.touch()

    def propnames(self):
        return sorted(self.props) + ['Children', 'Parent', 'Type']

    def delete_handle(self):
        if not self.valid or self.props.get('BeingDeleted'):
            return
        if DELETE_HOOK[0] is not None and self.props.get('DeleteFcn') not in (None, ''):
            # DeleteFcn runs first, while the object is still there to read
            self.props['BeingDeleted'] = True
            DELETE_HOOK[0](self)
        self.touch()
        for c in list(self.children):
            c.delete_handle()
        self.valid = False
        if self.parent is not None and self in self.parent.children:
            self.parent.children.remove(self)
        STORE.objects.pop(self.id, None)
        self.on_delete()

    def on_delete(self):
        pass

    # default property values: set(0, 'DefaultAxesFontSize', 14) on the root, a
    # figure or a container, for the objects made in it from then on
    def set_default(self, cls, prop, value):
        d = self.__dict__.setdefault('user_defaults', {})
        if type(value) in (Char, Str) and py_str(value).lower() == 'remove':
            d.pop((cls, prop), None)
            return
        d[(cls, prop)] = value
        USER_DEFAULTS[0] = True

    def default_value(self, kind, cls, prop):
        if kind == 'default':
            # the nearest set: this object, its ancestors, the root
            o = self
            while o is not None:
                d = o.__dict__.get('user_defaults')
                if d and (cls, prop) in d:
                    return d[(cls, prop)]
                o = o.parent if o.parent is not None else (ROOT if o is not ROOT else None)
        v = cls.DEFAULTS.get(prop)
        if callable(v) and not isinstance(v, FH):
            v = v()
        return export_value(prop, v)

    def apply_defaults(self):
        chain = []
        o = self.parent
        while o is not None:
            chain.append(o)
            o = o.parent
        if ROOT not in chain:
            chain.append(ROOT)
        for o in reversed(chain):          # the nearest last, so it wins
            d = o.__dict__.get('user_defaults')
            if not d:
                continue
            for (cls, prop), v in d.items():
                if type(self) is cls:
                    try:
                        self.set_value(prop, v)
                    except Exception:
                        pass

    def number_value(self):
        """The object's handle as a number: a figure's number, 0 for the root,
        and for the rest a number that is never whole, so never a figure's."""
        if self.TYPE == 'figure':
            return float(self.props.get('Number', self.id))
        return 0.0 if self.TYPE == 'root' else self.id + HANDLE_FRACTION

    def display_lines(self):
        name = self.CLASSNAME.split('.')[-1]
        lines = [f'  {name} with properties:', '']
        shown = self.SHOWN if hasattr(self, 'SHOWN') else list(self.props)[:8]
        w = max([len(s) for s in shown] + [1])
        from .display import summary
        for k in shown:
            v = self.get_value(k) if k in self.props else self.getprop(k)
            lines.append('    ' + k.rjust(w) + ': ' + summary(v))
        lines.append('')
        lines.append('  Show all properties')
        return lines

    def equals(self, other):
        return self is other

    def to_text(self):
        return str(self.number_value())


def export_value(k, v):
    """A stored property as a value of the language."""
    if v is None:
        return EMPTY()
    if isinstance(v, tuple) and len(v) == 3 and all(isinstance(x, float) for x in v):
        return np.array([list(v)])
    if isinstance(v, str):
        return Char.of(v)
    if isinstance(v, bool):
        return Char.of('on') if v else Char.of('off')
    if isinstance(v, list):
        if all(isinstance(x, str) for x in v):
            return Cell.of_list([Char.of(x) for x in v])
        return Cell.of_list(v)
    if isinstance(v, (int, np.integer)) and not isinstance(v, bool):
        return float(v)
    return v


_COLOR_PROPS = {'Color': ('none',), 'MarkerFaceColor': ('none', 'auto', 'flat'), 'MarkerEdgeColor': ('none', 'auto', 'flat'),
                'FaceColor': ('none', 'flat', 'interp', 'texturemap', 'auto'), 'EdgeColor': ('none', 'flat', 'interp', 'auto'),
                'XColor': ('none',), 'YColor': ('none',), 'ZColor': ('none',), 'BackgroundColor': ('none',),
                'GridColor': ('none',), 'MinorGridColor': ('none',), 'TextColor': ('none',), 'MarkerEdge': ('none',),
                'ForegroundColor': (), 'HighlightColor': (), 'ShadowColor': ()}
_ONOFF = {'Visible', 'Box', 'XGrid', 'YGrid', 'ZGrid', 'XMinorGrid', 'YMinorGrid', 'ZMinorGrid', 'XMinorTick', 'YMinorTick',
          'ZMinorTick', 'Clipping', 'HitTest', 'NumberTitle', 'AutoUpdate', 'Resize', 'ShowText', 'Selected',
          'Interruptible', 'BeingDeleted', 'SelectionHighlight', 'Separator', 'Checked', 'State', 'Enable', 'IntegerHandle',
          'DockControls', 'RowStriping', 'ShowHiddenHandles', 'DoubleBuffer', 'BackingStore', 'ShareColors',
          'GraphicsSmoothing', 'LineSmoothing', 'Editing', 'FontSmoothing'}


def import_value(obj, k, v):
    """A value of the language stored as a property."""
    if k == 'UIContextMenu':
        if isinstance(v, HArr) and v.a.size == 1:
            v = v.a.flat[0]
        return v if isinstance(v, GObj) and v.TYPE == 'uicontextmenu' else None
    if k == 'Enable' and type(v) in (Char, Str) and py_str(v).lower() == 'inactive':
        return 'inactive'
    if k in _COLOR_PROPS:
        c = to_color(v, _COLOR_PROPS[k])
        return c if c != 'none' or k != 'Color' else 'none'
    if k in _ONOFF:
        if type(v) in (Char, Str):
            s = py_str(v).lower()
            if s not in ('on', 'off'):
                raise gerr(f"Invalid value for {k}: use 'on' or 'off'.", 'MATLAB:datatypes:onoffboolean:IncorrectValue')
            return s == 'on'
        try:
            return bool(np.asarray(v if type(v) is not Char else v.a).reshape(-1)[0])
        except Exception:
            raise gerr(f"Invalid value for {k}: use 'on' or 'off'.")
    if type(v) is Char:
        return v.str() if v.a.shape[0] <= 1 else v.row_strs()
    if type(v) is Str:
        if v.a.size == 1:
            return v.a.flat[0] or ''
        return [s or '' for s in v.a.reshape(-1, order='F')]
    if type(v) is Cell and k in ('String', 'XTickLabel', 'YTickLabel', 'ZTickLabel', 'TickLabels', 'LegendStrings', 'Labels'):
        return [py_str(x) if type(x) in (Char, Str) else (str(x) if type(x) is float else '') for x in v.a.reshape(-1, order='F')]
    return share(v)


class Store:
    def __init__(self):
        self.objects = {}
        self.figures = {}         # number -> Figure
        self.current = None       # the current figure
        self.dirty = set()
        self.closed = []          # figure ids the page must remove


STORE = Store()


class Root(GObj):
    TYPE = 'root'
    CLASSNAME = 'matlab.ui.Root'
    DEFAULTS = {'ScreenSize': lambda: np.array([[1, 1, 1440, 900]], F64), 'Units': 'pixels', 'ShowHiddenHandles': False}

    def getprop(self, name):
        if name.lower() == 'currentfigure':
            return STORE.current if STORE.current is not None and STORE.current.valid else EMPTY()
        if name.lower() == 'children':
            from .builtins.graphics import shown_test
            shown = shown_test()
            return HArr.of([f for f in sorted(STORE.figures.values(), key=lambda f: -f.order) if shown(f)], col=True)
        if name.lower() == 'callbackobject':
            from .uievents import gcbo
            o = gcbo()
            return o if o is not None else EMPTY()
        return super().getprop(name)

    def setprop(self, name, value):
        if name.lower() == 'currentfigure':
            STORE.current = value
            return
        return super().setprop(name, value)


def _cm_default():
    from .colormaps import colormap_by_name
    return colormap_by_name('parula', 256)


_order = itertools.count(1)


class Figure(GObj):
    TYPE = 'figure'
    CLASSNAME = 'matlab.ui.Figure'
    DEFAULTS = {'Number': 1.0, 'Name': '', 'NumberTitle': True, 'Position': lambda: np.array([[680, 458, 560, 420]], F64),
                'Color': (0.94, 0.94, 0.94), 'Colormap': _cm_default, 'Visible': True, 'WindowStyle': 'normal',
                'Units': 'pixels', 'NextPlot': 'add', 'Tag': '', 'UserData': lambda: EMPTY(), 'CurrentAxes': None,
                'MenuBar': 'figure', 'ToolBar': 'auto', 'Resize': True, 'PaperPositionMode': 'auto',
                'CloseRequestFcn': 'closereq', 'HandleVisibility': 'on', 'InvertHardcopy': 'on', 'Renderer': 'opengl',
                'KeyPressFcn': '', 'KeyReleaseFcn': '', 'WindowKeyPressFcn': '', 'WindowKeyReleaseFcn': '',
                'WindowButtonDownFcn': '', 'WindowButtonUpFcn': '', 'WindowButtonMotionFcn': '', 'WindowScrollWheelFcn': '',
                'ButtonDownFcn': '', 'SizeChangedFcn': '', 'ResizeFcn': '', 'CreateFcn': '', 'DeleteFcn': '',
                'CurrentCharacter': '', 'CurrentKey': '', 'CurrentModifier': lambda: [], 'CurrentObject': None,
                'CurrentPoint': lambda: np.array([[0.0, 0.0]]), 'SelectionType': 'normal', 'Pointer': 'arrow',
                'UIContextMenu': None, 'Interruptible': True, 'BusyAction': 'queue', 'IntegerHandle': True,
                'DockControls': True, 'WindowState': 'normal', 'FileName': '', 'Clipping': True, 'HitTest': True,
                'BeingDeleted': False}
    ALIASES = {'ContextMenu': 'UIContextMenu'}
    SHOWN = ['Number', 'Name', 'Color', 'Position', 'Units']

    def __init__(self, number):
        super().__init__(None)
        self.props['Number'] = float(number)
        self.version = 1
        self.order = next(_order)
        self.layout = None        # tiledlayout grid, when made
        if number < 0:
            # a dialog's window: no number of its own, and no current figure
            self.props['IntegerHandle'] = False
            self.props['HandleVisibility'] = 'callback'
            self.props['NumberTitle'] = False
        STORE.figures[number] = self
        STORE.dirty.add(self)

    @property
    def is_dialog(self):
        return self.props['Number'] < 0

    def get_value(self, k):
        if k == 'CurrentAxes':
            a = self.props.get('CurrentAxes')
            return a if a is not None and a.valid else EMPTY()
        if k == 'Number' and self.is_dialog:
            return EMPTY()
        if k == 'CurrentObject':
            o = self.props.get('CurrentObject')
            return o if o is not None and o.valid else EMPTY()
        return super().get_value(k)

    def set_value(self, k, value):
        if k == 'CurrentAxes':
            self.props[k] = value
            return
        if k == 'Colormap':
            from .colormaps import as_colormap
            self.props[k] = as_colormap(value)
            return
        if k == 'Position':
            a = np.asarray(value, float).reshape(1, -1)
            if a.size != 4:
                raise gerr('Value must be a 4-element vector.')
            self.props[k] = a
            # a size the program chose: the page opens the window at it, not at one remembered
            self.placed = True
            return
        if k in ('CurrentObject', 'UIContextMenu'):
            self.props[k] = value if isinstance(value, GObj) else None
            return
        if k == 'Pointer':
            self.props[k] = py_str(value).lower()
            return
        super().set_value(k, value)

    def number_value(self):
        return float(self.props['Number'])

    def on_delete(self):
        n = int(self.props['Number'])
        if STORE.figures.get(n) is self:
            del STORE.figures[n]
        STORE.closed.append(self.id)
        STORE.dirty.discard(self)
        if STORE.current is self:
            rest = sorted(STORE.figures.values(), key=lambda f: -f.order)
            STORE.current = rest[0] if rest else None

    def axes_list(self):
        return [c for c in self.children if c.valid and c.TYPE == 'axes']

    def display_lines(self):
        p = self.props
        pos = p['Position'].reshape(-1)
        return ['  Figure (' + str(int(p['Number'])) + (': ' + p['Name'] if p['Name'] else '') + ') with properties:', '',
                f"      Number: {int(p['Number'])}", f"        Name: '{p['Name']}'",
                f"       Color: [{' '.join(f'{x:g}' for x in p['Color'])}]",
                f"    Position: [{' '.join(f'{x:g}' for x in pos)}]", "       Units: 'pixels'", '', '  Show all properties']


class Axes(GObj):
    TYPE = 'axes'
    CLASSNAME = 'matlab.graphics.axis.Axes'
    DEFAULTS = {
        'Position': lambda: np.array([[0.13, 0.11, 0.775, 0.815]]), 'OuterPosition': lambda: np.array([[0, 0, 1, 1]], F64),
        'XLim': lambda: np.array([[0.0, 1.0]]), 'YLim': lambda: np.array([[0.0, 1.0]]), 'ZLim': lambda: np.array([[0.0, 1.0]]),
        'XLimMode': 'auto', 'YLimMode': 'auto', 'ZLimMode': 'auto',
        'XTick': lambda: EMPTY(), 'YTick': lambda: EMPTY(), 'ZTick': lambda: EMPTY(),
        'XTickMode': 'auto', 'YTickMode': 'auto', 'ZTickMode': 'auto',
        'XTickLabel': None, 'YTickLabel': None, 'ZTickLabel': None,
        'XTickLabelMode': 'auto', 'YTickLabelMode': 'auto', 'ZTickLabelMode': 'auto',
        'XTickLabelRotation': 0.0, 'YTickLabelRotation': 0.0,
        'XScale': 'linear', 'YScale': 'linear', 'ZScale': 'linear',
        'XDir': 'normal', 'YDir': 'normal', 'ZDir': 'normal',
        'XGrid': False, 'YGrid': False, 'ZGrid': False, 'XMinorGrid': False, 'YMinorGrid': False, 'ZMinorGrid': False,
        'XMinorTick': False, 'YMinorTick': False, 'ZMinorTick': False,
        'Box': False, 'Color': (1.0, 1.0, 1.0), 'XColor': AXIS_COLOR, 'YColor': AXIS_COLOR, 'ZColor': AXIS_COLOR,
        'GridColor': (0.15, 0.15, 0.15), 'GridAlpha': 0.15, 'MinorGridAlpha': 0.25, 'GridLineStyle': '-',
        'FontSize': 10.0, 'FontName': 'Helvetica', 'FontWeight': 'normal', 'LineWidth': 0.5, 'TitleFontSizeMultiplier': 1.1,
        'LabelFontSizeMultiplier': 1.1, 'TitleFontWeight': 'bold', 'TickDir': 'in', 'TickLength': lambda: np.array([[0.01, 0.025]]),
        'NextPlot': 'replace', 'ColorOrder': lambda: COLOR_ORDER.copy(), 'ColorOrderIndex': 1.0, 'LineStyleOrder': '-',
        'LineStyleOrderIndex': 1.0, 'CLim': lambda: np.array([[0.0, 1.0]]), 'CLimMode': 'auto', 'View': lambda: np.array([[0.0, 90.0]]),
        'DataAspectRatio': lambda: np.array([[1.0, 1.0, 1.0]]), 'DataAspectRatioMode': 'auto',
        'PlotBoxAspectRatio': lambda: np.array([[1.0, 1.0, 1.0]]), 'PlotBoxAspectRatioMode': 'auto',
        'XAxisLocation': 'bottom', 'YAxisLocation': 'left', 'Layer': 'bottom', 'Visible': True, 'Tag': '',
        'UserData': lambda: EMPTY(), 'Units': 'normalized', 'Clipping': True, 'Projection': 'orthographic',
        'TickLabelInterpreter': 'tex', 'Colormap': None, 'ActivePositionProperty': 'outerposition', 'SortMethod': 'depth',
        'AmbientLightColor': (1.0, 1.0, 1.0), 'XAxis': None, 'YAxis': None,
    }
    SHOWN = ['XLim', 'YLim', 'XScale', 'YScale', 'GridLineStyle', 'Position', 'Units']

    def __init__(self, parent, **props):
        super().__init__(parent, **props)
        self.title = Text(None, String='', hidden=True)
        self.title.props['FontWeight'] = 'bold'
        self.xlabel = Text(None, String='')
        self.ylabel = Text(None, String='')
        self.zlabel = Text(None, String='')
        self.subtitle = Text(None, String='')
        for t in (self.title, self.xlabel, self.ylabel, self.zlabel, self.subtitle):
            t.parent = self
            t.hidden = True
        self.legend = None
        self.colorbar = None
        self.kind = 'cartesian'        # or 'polar'
        self.yy = None                 # yyaxis: {'side': 'left'|'right', 'right': Axes}
        self.yy_owner = None
        self.layout_cell = None
        self.is3d_hint = False

    def get_value(self, k):
        if k in ('XLim', 'YLim', 'ZLim') and self.props[k + 'Mode'] == 'auto':
            from .glayout import auto_limits
            lims = auto_limits(self)
            return np.array([lims[k]])
        if k in ('XTick', 'YTick', 'ZTick') and self.props[k + 'Mode'] == 'auto':
            from .glayout import auto_ticks
            return np.array([auto_ticks(self, k[0])]) if True else EMPTY()
        if k in ('XTickLabel', 'YTickLabel', 'ZTickLabel') and self.props[k + 'Mode'] == 'auto':
            from .glayout import auto_ticks, tick_labels
            t = auto_ticks(self, k[0])
            labels, _ = tick_labels(t, self.props[k[0] + 'Scale'])
            return Cell.of_list([Char.of(s) for s in labels], (len(labels), 1))
        if k == 'CLim' and self.props['CLimMode'] == 'auto':
            from .glayout import auto_clim
            return np.array([auto_clim(self)])
        if k == 'Title':
            return self.title
        if k == 'XLabel':
            return self.xlabel
        if k == 'YLabel':
            return self.ylabel
        if k == 'ZLabel':
            return self.zlabel
        if k == 'Legend':
            return self.legend if self.legend is not None and self.legend.valid else EMPTY()
        if k == 'Colormap':
            c = self.props.get('Colormap')
            if c is None:
                f = self.figure()
                return f.props['Colormap'] if f is not None else _cm_default()
            return c
        if k == 'XTickLabel' or k == 'YTickLabel' or k == 'ZTickLabel':
            v = self.props.get(k)
            return Cell.of_list([Char.of(s) for s in (v or [])], (len(v or []), 1))
        return super().get_value(k)

    def set_value(self, k, value):
        if k in ('XLim', 'YLim', 'ZLim', 'CLim'):
            a = np.asarray(value if type(value) is not float else [value], float).reshape(-1)
            if a.size != 2:
                raise gerr('Value must be a 1x2 vector of numeric type in which the second element is larger than the first and may be Inf.', 'MATLAB:hg:shaped_arrays:LimitsWithInfsPredicate')
            lo, hi = float(a[0]), float(a[1])
            if not lo < hi:
                raise gerr('Value must be a 1x2 vector of numeric type in which the second element is larger than the first and may be Inf.', 'MATLAB:hg:shaped_arrays:LimitsWithInfsPredicate')
            if math.isinf(lo) or math.isinf(hi):
                from .glayout import auto_limits, auto_clim
                auto = auto_clim(self) if k == 'CLim' else auto_limits(self)[k]
                lo = auto[0] if math.isinf(lo) else lo
                hi = auto[1] if math.isinf(hi) else hi
            self.props[k] = np.array([[lo, hi]])
            self.props[k + 'Mode'] = 'manual'
            return
        if k in ('XTick', 'YTick', 'ZTick'):
            a = np.asarray(value, float).reshape(1, -1) if numel(value) else np.zeros((1, 0))
            self.props[k] = a
            self.props[k + 'Mode'] = 'manual'
            return
        if k in ('XTickLabel', 'YTickLabel', 'ZTickLabel'):
            if type(value) is Cell:
                labels = [py_str(x) if type(x) in (Char, Str) else _num_label(x) for x in value.a.reshape(-1, order='F')]
            elif type(value) is Char:
                labels = value.row_strs() if value.a.shape[0] > 1 else ([value.str()] if value.a.size else [])
            elif type(value) is Str:
                labels = [s or '' for s in value.a.reshape(-1, order='F')]
            else:
                labels = [_num_label(x) for x in np.asarray(value, float).reshape(-1)]
            self.props[k] = labels
            self.props[k + 'Mode'] = 'manual'
            return
        if k in ('XLimMode', 'YLimMode', 'ZLimMode', 'XTickMode', 'YTickMode', 'ZTickMode', 'CLimMode',
                 'XTickLabelMode', 'YTickLabelMode', 'ZTickLabelMode', 'DataAspectRatioMode', 'PlotBoxAspectRatioMode'):
            s = py_str(value).lower()
            if s not in ('auto', 'manual'):
                raise gerr(f"Invalid value for {k}: use 'auto' or 'manual'.")
            self.props[k] = s
            return
        if k == 'View':
            a = np.asarray(value, float).reshape(-1)
            if a.size == 2:
                self.props[k] = a.reshape(1, 2)
            return
        if k in ('DataAspectRatio', 'PlotBoxAspectRatio'):
            a = np.asarray(value, float).reshape(-1)
            if a.size == 3:
                self.props[k] = a.reshape(1, 3)
                self.props[k + 'Mode'] = 'manual'
            return
        if k == 'Colormap':
            from .colormaps import as_colormap
            self.props[k] = as_colormap(value)
            return
        if k in ('Title', 'XLabel', 'YLabel', 'ZLabel'):
            t = {'Title': self.title, 'XLabel': self.xlabel, 'YLabel': self.ylabel, 'ZLabel': self.zlabel}[k]
            if isinstance(value, Text):
                t.props.update(value.props)
            else:
                t.set_value('String', value)
            return
        if k in ('XScale', 'YScale', 'ZScale'):
            s = py_str(value).lower()
            if s not in ('linear', 'log'):
                raise gerr(f"Invalid value for {k}: use 'linear' or 'log'.")
            self.props[k] = s
            return
        if k == 'ColorOrder':
            a = np.asarray(value, float)
            if a.ndim != 2 or a.shape[1] != 3:
                raise gerr('ColorOrder must be an m-by-3 matrix of RGB values.')
            self.props[k] = a
            return
        if k in ('Units', 'Position', 'CurrentPoint'):
            from .uiobjects import set_placed
            set_placed(self, k, value)
            return
        super().set_value(k, value)

    def plot_children(self):
        return [c for c in self.children if c.valid and c.TYPE not in ('text', 'light') and not getattr(c, 'hidden', False)]

    def is3d(self):
        v = self.props['View'].reshape(-1)
        return not (abs(v[1]) == 90 and v[0] % 90 == 0 and abs(v[1]) == 90) or self.kind == '3d'

    def next_color(self):
        """The color for the next line (ColorOrder, cycled; held axes go on)."""
        co = self.props['ColorOrder']
        i = int(self.props['ColorOrderIndex']) - 1
        c = co[i % co.shape[0]]
        self.props['ColorOrderIndex'] = float(i % co.shape[0] + 2)
        return tuple(float(x) for x in c)

    def reset_for_plot(self):
        """A new plot in axes that are not held: what was there goes, and the
        axes' settings return to their defaults (except Position)."""
        for c in list(self.children):
            c.delete_handle()
        keep = {k: self.props[k] for k in ('Position', 'OuterPosition', 'Units', 'Tag')}
        hold_keep = {}
        for k, v in Axes.DEFAULTS.items():
            self.props[k] = v() if callable(v) else v
        self.props.update(keep)
        self.title.props['String'] = ''
        self.xlabel.props['String'] = ''
        self.ylabel.props['String'] = ''
        self.zlabel.props['String'] = ''
        self.subtitle.props['String'] = ''
        if self.legend is not None:
            self.legend.delete_handle()
            self.legend = None
        if self.colorbar is not None:
            self.colorbar.delete_handle()
            self.colorbar = None
        self.kind = 'cartesian'
        self.touch()


def _num_label(x):
    if type(x) in (Char, Str):
        return py_str(x)
    try:
        v = float(np.asarray(x).reshape(-1)[0])
    except Exception:
        return ''
    return f'{v:g}'


class Line(GObj):
    TYPE = 'line'
    CLASSNAME = 'matlab.graphics.chart.primitive.Line'
    DEFAULTS = {'XData': lambda: np.zeros((1, 0)), 'YData': lambda: np.zeros((1, 0)), 'ZData': lambda: np.zeros((1, 0)),
                'Color': (0.0, 0.447, 0.741), 'LineStyle': '-', 'LineWidth': 0.5, 'Marker': 'none', 'MarkerSize': 6.0,
                'MarkerFaceColor': 'none', 'MarkerEdgeColor': 'auto', 'MarkerIndices': None, 'DisplayName': '', 'Visible': True,
                'Tag': '', 'UserData': lambda: EMPTY(), 'Clipping': True, 'SeriesIndex': 1.0, 'AlignVertexCenters': False}
    SHOWN = ['Color', 'LineStyle', 'LineWidth', 'Marker', 'MarkerSize', 'MarkerFaceColor', 'XData', 'YData', 'ZData']

    def set_value(self, k, value):
        if k in ('XData', 'YData', 'ZData'):
            a = np.asarray(value.a if type(value) is Char else value, float) if numel(value) else np.zeros((1, 0))
            self.props[k] = a.reshape(1, -1)
            return
        if k == 'LineStyle':
            s = py_str(value)
            if s not in ('-', '--', ':', '-.', 'none'):
                raise gerr(f"'{s}' is not a valid value for LineStyle. Use one of these values: '-' | '--' | ':' | '-.' | 'none'.")
            self.props[k] = s
            return
        if k == 'Marker':
            s = py_str(value).lower()
            m = MARKER_WORDS.get(s, MARKERS.get(s))
            if m is None:
                raise gerr(f"'{py_str(value)}' is not a valid value for Marker.")
            self.props[k] = m
            return
        super().set_value(k, value)


class Surface(GObj):
    TYPE = 'surface'
    CLASSNAME = 'matlab.graphics.chart.primitive.Surface'
    DEFAULTS = {'XData': lambda: EMPTY(), 'YData': lambda: EMPTY(), 'ZData': lambda: EMPTY(), 'CData': lambda: EMPTY(),
                'FaceColor': 'flat', 'EdgeColor': (0.0, 0.0, 0.0), 'FaceAlpha': 1.0, 'EdgeAlpha': 1.0, 'LineStyle': '-',
                'LineWidth': 0.5, 'MeshStyle': 'both', 'Marker': 'none', 'MarkerSize': 6.0, 'DisplayName': '', 'Visible': True,
                'FaceLighting': 'flat', 'EdgeLighting': 'none', 'Tag': '', 'UserData': lambda: EMPTY(), 'CDataMapping': 'scaled',
                'AmbientStrength': 0.3, 'DiffuseStrength': 0.6, 'SpecularStrength': 0.9, 'SpecularExponent': 10.0, 'BackFaceLighting': 'reverselit'}
    SHOWN = ['EdgeColor', 'LineStyle', 'FaceColor', 'FaceLighting', 'FaceAlpha', 'XData', 'YData', 'ZData', 'CData']

    def set_value(self, k, value):
        if k in ('FaceAlpha', 'EdgeAlpha') and type(value) in (Char, Str):
            self.props[k] = py_str(value)
            return
        super().set_value(k, value)


class Patch(GObj):
    TYPE = 'patch'
    CLASSNAME = 'matlab.graphics.primitive.Patch'
    DEFAULTS = {'XData': lambda: EMPTY(), 'YData': lambda: EMPTY(), 'ZData': lambda: EMPTY(), 'Faces': lambda: EMPTY(),
                'Vertices': lambda: EMPTY(), 'FaceColor': (0.0, 0.0, 0.0), 'EdgeColor': (0.0, 0.0, 0.0), 'FaceAlpha': 1.0,
                'EdgeAlpha': 1.0, 'LineStyle': '-', 'LineWidth': 0.5, 'CData': lambda: EMPTY(), 'FaceVertexCData': lambda: EMPTY(),
                'Marker': 'none', 'MarkerSize': 6.0, 'MarkerFaceColor': 'none', 'DisplayName': '', 'Visible': True, 'Tag': '',
                'UserData': lambda: EMPTY(), 'FaceLighting': 'flat', 'CDataMapping': 'scaled'}
    SHOWN = ['FaceColor', 'FaceAlpha', 'EdgeColor', 'LineStyle', 'Faces', 'Vertices']


class Image(GObj):
    TYPE = 'image'
    CLASSNAME = 'matlab.graphics.primitive.Image'
    DEFAULTS = {'CData': lambda: EMPTY(), 'XData': lambda: np.array([[1.0, 1.0]]), 'YData': lambda: np.array([[1.0, 1.0]]),
                'CDataMapping': 'direct', 'AlphaData': 1.0, 'Visible': True, 'Tag': '', 'UserData': lambda: EMPTY(), 'DisplayName': ''}
    SHOWN = ['CData', 'CDataMapping']


class Text(GObj):
    TYPE = 'text'
    CLASSNAME = 'matlab.graphics.primitive.Text'
    DEFAULTS = {'String': '', 'Position': lambda: np.array([[0.0, 0.0, 0.0]]), 'FontSize': 10.0, 'FontName': 'Helvetica',
                'FontWeight': 'normal', 'FontAngle': 'normal', 'Color': (0.0, 0.0, 0.0), 'HorizontalAlignment': 'left',
                'VerticalAlignment': 'middle', 'Rotation': 0.0, 'Interpreter': 'tex', 'BackgroundColor': 'none',
                'EdgeColor': 'none', 'LineWidth': 0.5, 'Margin': 3.0, 'Visible': True, 'Units': 'data', 'Tag': '',
                'UserData': lambda: EMPTY(), 'Clipping': False}
    SHOWN = ['String', 'FontSize', 'FontWeight', 'FontName', 'Color', 'HorizontalAlignment', 'Position', 'Units']

    def __init__(self, parent=None, **props):
        hidden = props.pop('hidden', False)
        super().__init__(parent, **props)
        self.hidden = hidden

    def set_value(self, k, value):
        if k == 'String':
            if type(value) is Cell:
                self.props[k] = [py_str(x) if type(x) in (Char, Str) else _num_label(x) for x in value.a.reshape(-1, order='F')]
            elif type(value) is Char:
                self.props[k] = value.row_strs() if value.a.shape[0] > 1 else value.str()
            elif type(value) is Str:
                self.props[k] = [s or '' for s in value.a.reshape(-1, order='F')] if value.a.size != 1 else (value.a.flat[0] or '')
            elif type(value) in (float, np.ndarray, bool):
                self.props[k] = ' '.join(_num_label(x) for x in np.asarray(value).reshape(-1)) if numel(value) else ''
            else:
                self.props[k] = str(value)
            return
        if k == 'Position':
            a = np.asarray(value, float).reshape(-1)
            if a.size == 2:
                a = np.append(a, 0.0)
            self.props[k] = a.reshape(1, -1)
            return
        if k == 'Units':
            from .uiobjects import set_text_units
            set_text_units(self, value)
            return
        super().set_value(k, value)

    def get_value(self, k):
        if k == 'String':
            v = self.props.get('String', '')
            if isinstance(v, list):
                return Cell.of_list([Char.of(s) for s in v], (len(v), 1))
            return Char.of(v)
        return super().get_value(k)


class Legend(GObj):
    TYPE = 'legend'
    CLASSNAME = 'matlab.graphics.illustration.Legend'
    DEFAULTS = {'String': lambda: [], 'Location': 'northeast', 'Orientation': 'vertical', 'Box': True, 'FontSize': 9.0,
                'TextColor': (0.0, 0.0, 0.0), 'Color': (1.0, 1.0, 1.0), 'EdgeColor': (0.15, 0.15, 0.15), 'Visible': True,
                'Interpreter': 'tex', 'AutoUpdate': True, 'NumColumns': 1.0, 'Title': '', 'Position': lambda: np.array([[0.0, 0.0, 0.0, 0.0]]),
                'Tag': '', 'UserData': lambda: EMPTY(), 'ItemHitFcn': ''}
    SHOWN = ['String', 'Location', 'Orientation', 'FontSize', 'Position', 'Units']

    def __init__(self, axes, entries):
        super().__init__(axes.figure())
        self.axes = axes
        self.entries = entries      # the plotted objects the legend names
        self.hidden = True

    def get_value(self, k):
        if k == 'String':
            return Cell.of_list([Char.of(e.props.get('DisplayName', '')) for e in self.entries if e.valid])
        return super().get_value(k)

    def set_value(self, k, value):
        if k == 'String':
            names = [py_str(x) for x in value.a.reshape(-1, order='F')] if type(value) is Cell else [py_str(value)]
            for e, n in zip(self.entries, names):
                e.props['DisplayName'] = n
            return
        if k == 'Location':
            self.props[k] = py_str(value).lower()
            return
        super().set_value(k, value)


class Colorbar(GObj):
    TYPE = 'colorbar'
    CLASSNAME = 'matlab.graphics.illustration.ColorBar'
    DEFAULTS = {'Location': 'eastoutside', 'Ticks': None, 'TickLabels': None, 'Limits': None, 'FontSize': 9.0,
                'Color': AXIS_COLOR, 'Visible': True, 'Direction': 'normal', 'Position': lambda: np.array([[0.0, 0.0, 0.0, 0.0]]),
                'Tag': '', 'UserData': lambda: EMPTY(), 'TickDirection': 'in', 'Box': True}
    SHOWN = ['Location', 'Limits', 'FontSize', 'Position', 'Units']

    def __init__(self, axes):
        super().__init__(axes.figure())
        self.axes = axes
        self.label = Text(None, String='')
        self.label.parent = self
        self.label.hidden = True
        self.hidden = True

    def get_value(self, k):
        if k == 'Label':
            return self.label
        if k == 'Limits':
            from .glayout import auto_clim
            return np.array([auto_clim(self.axes) if self.axes.props['CLimMode'] == 'auto' else list(self.axes.props['CLim'].reshape(-1))])
        if k == 'Ticks':
            v = self.props.get('Ticks')
            if v is None:
                from .glayout import nice_ticks, auto_clim
                lo, hi = auto_clim(self.axes) if self.axes.props['CLimMode'] == 'auto' else self.axes.props['CLim'].reshape(-1)
                return np.array([nice_ticks(lo, hi, 9)])
            return v
        return super().get_value(k)

    def set_value(self, k, value):
        if k == 'Ticks':
            self.props[k] = np.asarray(value, float).reshape(1, -1)
            return
        if k == 'Limits':
            a = np.asarray(value, float).reshape(-1)
            self.axes.props['CLim'] = a.reshape(1, 2)
            self.axes.props['CLimMode'] = 'manual'
            return
        super().set_value(k, value)


class Light(GObj):
    TYPE = 'light'
    CLASSNAME = 'matlab.graphics.primitive.Light'
    DEFAULTS = {'Position': lambda: np.array([[1.0, 0.0, 1.0]]), 'Style': 'infinite', 'Color': (1.0, 1.0, 1.0), 'Visible': True, 'Tag': ''}


class Series(GObj):
    """A chart made of simple marks: bar, stem, stairs, area, errorbar,
    scatter, histogram, contour, quiver, pie. Its kind says how the page
    draws it."""
    TYPE = 'series'
    CLASSNAME = 'matlab.graphics.chart.primitive.Series'
    DEFAULTS = {'XData': lambda: EMPTY(), 'YData': lambda: EMPTY(), 'ZData': lambda: EMPTY(), 'CData': lambda: EMPTY(),
                'UData': lambda: EMPTY(), 'VData': lambda: EMPTY(), 'WData': lambda: EMPTY(),
                'FaceColor': (0.0, 0.447, 0.741), 'EdgeColor': (0.0, 0.0, 0.0), 'Color': (0.0, 0.447, 0.741),
                'LineStyle': '-', 'LineWidth': 0.5, 'Marker': 'none', 'MarkerSize': 6.0, 'MarkerFaceColor': 'none',
                'MarkerEdgeColor': 'flat', 'FaceAlpha': 1.0, 'EdgeAlpha': 1.0, 'MarkerFaceAlpha': 1.0, 'BarWidth': 0.8,
                'BaseValue': 0.0, 'DisplayName': '', 'Visible': True, 'Tag': '', 'UserData': lambda: EMPTY(),
                'SizeData': 36.0, 'LevelList': lambda: EMPTY(), 'LevelListMode': 'auto', 'ShowText': False, 'Fill': False,
                'BinEdges': lambda: EMPTY(), 'Values': lambda: EMPTY(), 'Normalization': 'count', 'NumBins': 0.0,
                'BinWidth': 0.0, 'AutoScaleFactor': 0.9, 'Horizontal': False, 'Labels': lambda: [], 'MaxHeadSize': 0.2,
                'YNegativeDelta': lambda: EMPTY(), 'YPositiveDelta': lambda: EMPTY(), 'XNegativeDelta': lambda: EMPTY(), 'XPositiveDelta': lambda: EMPTY(),
                'CapSize': 6.0, 'Stacked': False}

    CLASSNAMES = {'bar': 'matlab.graphics.chart.primitive.Bar', 'stem': 'matlab.graphics.chart.primitive.Stem',
                  'stair': 'matlab.graphics.chart.primitive.Stair', 'area': 'matlab.graphics.chart.primitive.Area',
                  'errorbar': 'matlab.graphics.chart.primitive.ErrorBar', 'scatter': 'matlab.graphics.chart.primitive.Scatter',
                  'histogram': 'matlab.graphics.chart.primitive.Histogram', 'contour': 'matlab.graphics.chart.primitive.Contour',
                  'quiver': 'matlab.graphics.chart.primitive.Quiver', 'pie': 'matlab.graphics.primitive.Patch'}

    def __init__(self, parent, kind, **props):
        super().__init__(parent, **props)
        self.kind = kind
        self.extra = {}

    @property
    def CLASSNAME(self):
        return self.CLASSNAMES.get(self.kind, 'matlab.graphics.chart.primitive.Series')

    @property
    def TYPE(self):
        return self.kind

    def get_value(self, k):
        if k == 'Values' and self.kind == 'histogram':
            return self.extra.get('values', EMPTY())
        if k == 'BinEdges' and self.kind == 'histogram':
            return self.extra.get('edges', EMPTY())
        return super().get_value(k)

    def set_value(self, k, value):
        if k in ('XData', 'YData', 'ZData', 'UData', 'VData', 'CData', 'SizeData'):
            self.props[k] = np.asarray(value, float) if numel(value) and type(value) is not Char else value
            if self.kind == 'histogram' and k == 'Data':
                pass
            return
        super().set_value(k, value)


class HArr(Obj):
    """An array of handles (graphics objects or other handle objects)."""
    __slots__ = ('a',)
    is_handle = True

    def __init__(self, a):
        self.a = _2d(np.asarray(a, object)) if not isinstance(a, np.ndarray) else _2d(a)

    @property
    def is_graphics(self):
        return any(getattr(x, 'is_graphics', False) for x in self.a.flat)

    @staticmethod
    def of(items, col=False):
        a = np.empty((len(items), 1) if col else (1, len(items)), object)
        for i, x in enumerate(items):
            a.reshape(-1)[i] = x
        return HArr(a)

    @property
    def shape(self):
        return self.a.shape

    @property
    def cls(self):
        if self.a.size:
            return class_of(self.a.flat[0])
        return 'matlab.graphics.Graphics'

    def getprop(self, name):
        if self.a.size == 1:
            return self.a.flat[0].getprop(name)
        raise MError('MATLAB:index:expected_one_output_from_expression', f'Expected one output from a curly brace or dot indexing expression, but there were {self.a.size} results.')

    def setprop(self, name, value):
        for h in self.a.flat:
            h.setprop(name, value)

    def propnames(self):
        return self.a.flat[0].propnames() if self.a.size else []

    def display_lines(self):
        n = self.a.size
        if n == 0:
            return [f'  {size_str(self.a.shape)} empty GraphicsPlaceholder array.']
        names = [getattr(h, 'CLASSNAME', class_of(h)).split('.')[-1] for h in self.a.flat]
        lines = [f'  {size_str(self.a.shape)} {names[0]} array:', '']
        for h in self.a.flat:
            nm = getattr(h, 'CLASSNAME', class_of(h)).split('.')[-1]
            lines.append(f'    {nm}' + (f"    ({h.props.get('DisplayName', '')})" if isinstance(h, GObj) and h.props.get('DisplayName') else ''))
        return lines

    def transposed(self):
        return HArr(self.a.T.copy())

    def number_value(self):
        return self.a.flat[0].number_value()


def cat_handles(axis, vals):
    parts = []
    for v in vals:
        if isinstance(v, HArr):
            parts.append(v.a)
        elif isinstance(v, Obj):
            a = np.empty((1, 1), object)
            a[0, 0] = v
            parts.append(a)
        elif isinstance(v, np.ndarray) and v.size == 0:
            continue
        elif isinstance(v, FH):
            raise MError('MATLAB:fhNonScalar', 'Nonscalar arrays of function handles are not allowed; use cell arrays instead.')
        else:
            raise MError('MATLAB:catenate:invalidType', f'Unable to concatenate a {class_of(v)} with graphics objects.')
    if not parts:
        return HArr(np.empty((0, 0), object))
    from .ops import _concat_arrays
    return HArr(_concat_arrays(parts, axis))


USER_DEFAULTS = [False]     # a default has been set somewhere: new objects look
_DEFAULT_NAME = re.compile(r'(default|factory)(.+)$', re.I)


def _default_types():
    from . import uiobjects as U
    return {'root': Root, 'figure': Figure, 'axes': Axes, 'line': Line, 'surface': Surface, 'patch': Patch, 'image': Image,
            'text': Text, 'light': Light, 'uicontrol': U.UIControl, 'uipanel': U.UIPanel, 'uibuttongroup': U.UIButtonGroup,
            'uitable': U.UITable, 'uitabgroup': U.UITabGroup, 'uitab': U.UITab, 'uimenu': U.UIMenu,
            'uicontextmenu': U.UIContextMenu, 'uitoolbar': U.UIToolbar, 'uipushtool': U.UIPushTool,
            'uitoggletool': U.UIToggleTool}


def split_default(name):
    """('default' or 'factory', the class, its property) of a name such as
    DefaultAxesFontSize or FactoryUicontrolPosition, else None."""
    m = _DEFAULT_NAME.match(name)
    if m is None:
        return None
    rest = m.group(2).lower()
    types = _default_types()
    for t in sorted(types, key=len, reverse=True):
        if rest.startswith(t) and len(rest) > len(t):
            prop = types[t].canon(rest[len(t):])
            if prop is not None:
                return m.group(1).lower(), types[t], prop
    return None


ROOT = Root(None)
HANDLE_FRACTION = 0.0001       # objects' handle numbers are their ids plus this


def handle_of_number(x):
    """The graphics object a handle number stands for, or None: 0 is the
    root, a whole number a figure, and the rest objects by their ids."""
    if x == 0:
        return ROOT
    if not math.isfinite(x):
        return None
    if x == int(x):
        f = STORE.figures.get(int(x))
        return f if f is not None and f.valid else None
    o = STORE.objects.get(int(math.floor(x)))
    return o if o is not None and o.valid and o.TYPE != 'figure' and o.number_value() == x else None


# ---- the description the page draws ------------------------------------------------------------

def _b64(a, dt='<f8'):
    a = np.ascontiguousarray(np.asarray(a, dtype=dt))
    return {'$': base64.b64encode(a.tobytes()).decode('ascii'), 'shape': list(a.shape), 'dt': 'f8' if dt == '<f8' else dt}


def _arr(v):
    """Numbers for the page: base64 float64 with their shape (row-major)."""
    if v is None:
        return None
    if type(v) is Char:
        return _b64(v.a.astype(float))
    a = np.asarray(v)
    if a.dtype == object:
        return None
    if a.dtype.kind == 'c':
        a = a.real
    if a.dtype.kind == 'b':
        a = a.astype(float)
    return _b64(a.astype(float))


def _color(c):
    if c is None:
        return 'none'
    if isinstance(c, str):
        return c
    return [round(float(x), 6) for x in c]


def has_callback(v):
    """Whether a callback property holds something to run."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return False
    return not (isinstance(v, np.ndarray) and v.size == 0)


def _interact_json(o):
    p = o.props
    cm = p.get('UIContextMenu')
    return {'bdf': has_callback(p.get('ButtonDownFcn')), 'hit': bool(p.get('HitTest', True)) and p.get('PickableParts', 'visible') != 'none',
            'cmenu': cm.id if cm is not None and cm.valid else None}


def _text_json(t):
    p = t.props
    s = p.get('String', '')
    return {'id': t.id, 'string': s if isinstance(s, list) else str(s), 'fontSize': float(p['FontSize']), 'fontUnits': p.get('FontUnits', 'points'),
            'fontWeight': p['FontWeight'], 'fontAngle': p['FontAngle'], 'color': _color(p['Color']),
            'rotation': float(p['Rotation']), 'interpreter': p['Interpreter'], 'visible': bool(p['Visible']),
            'halign': p['HorizontalAlignment'], 'valign': p['VerticalAlignment'],
            'position': [float(x) for x in np.asarray(p['Position'], float).reshape(-1)],
            'units': p['Units'], 'background': _color(p['BackgroundColor']), 'edge': _color(p['EdgeColor']),
            'fontName': p.get('FontName', 'Helvetica'), 'margin': float(p.get('Margin', 3.0)), 'lineWidth': float(p.get('LineWidth', 0.5))}


def _num(v):
    try:
        return float(np.asarray(v, float).reshape(-1)[0])
    except Exception:
        return None


def serialize_child(c, ax):
    p = c.props
    t = c.TYPE
    d = {'id': c.id, 'type': t, 'visible': bool(p.get('Visible', True)), 'displayName': p.get('DisplayName', ''),
         'clip': bool(p.get('Clipping', True))}
    d.update(_interact_json(c))
    if t == 'line':
        d.update(x=_arr(p['XData']), y=_arr(p['YData']), z=_arr(p['ZData']) if numel(p['ZData']) else None,
                 color=_color(p['Color']), lineStyle=p['LineStyle'], lineWidth=float(p['LineWidth']),
                 marker=p['Marker'], markerSize=float(p['MarkerSize']), mfc=_color(p['MarkerFaceColor']),
                 mec=_color(p['MarkerEdgeColor']))
        mi = p.get('MarkerIndices')
        if mi is not None and numel(mi):
            d['markerIndices'] = _arr(np.asarray(mi, float) - 1)
    elif t == 'surface':
        d.update(x=_arr(p['XData']), y=_arr(p['YData']), z=_arr(p['ZData']), c=_arr(p['CData']) if numel(p['CData']) else None,
                 faceColor=_color(p['FaceColor']), edgeColor=_color(p['EdgeColor']),
                 faceAlpha=p['FaceAlpha'] if isinstance(p['FaceAlpha'], str) else float(_num(p['FaceAlpha'])),
                 edgeAlpha=float(_num(p['EdgeAlpha'])) if not isinstance(p['EdgeAlpha'], str) else 1.0,
                 lineStyle=p['LineStyle'], lineWidth=float(p['LineWidth']), meshStyle=p['MeshStyle'],
                 lighting=p['FaceLighting'], marker=p['Marker'], markerSize=float(p['MarkerSize']),
                 cmapping=p['CDataMapping'])
    elif t == 'patch':
        d.update(x=_arr(p['XData']) if numel(p['XData']) else None, y=_arr(p['YData']) if numel(p['YData']) else None,
                 z=_arr(p['ZData']) if numel(p['ZData']) else None,
                 faces=_arr(p['Faces']) if numel(p['Faces']) else None, vertices=_arr(p['Vertices']) if numel(p['Vertices']) else None,
                 c=_arr(p['CData']) if numel(p['CData']) and type(p['CData']) is not Char else None,
                 fvc=_arr(p['FaceVertexCData']) if numel(p['FaceVertexCData']) else None,
                 faceColor=_color(p['FaceColor']), edgeColor=_color(p['EdgeColor']),
                 faceAlpha=float(_num(p['FaceAlpha'])) if not isinstance(p['FaceAlpha'], str) else 1.0,
                 edgeAlpha=float(_num(p['EdgeAlpha'])) if not isinstance(p['EdgeAlpha'], str) else 1.0,
                 lineStyle=p['LineStyle'], lineWidth=float(p['LineWidth']), marker=p['Marker'], markerSize=float(p['MarkerSize']),
                 mfc=_color(p['MarkerFaceColor']))
    elif t == 'image':
        cd = p['CData']
        a = np.asarray(cd.a if type(cd) is Char else cd)
        if a.dtype == np.uint8:
            a = a.astype(float) / 255.0 if a.ndim == 3 else a.astype(float)
        d.update(c=_arr(a), x=_arr(p['XData']), y=_arr(p['YData']), cmapping=p['CDataMapping'],
                 alpha=float(_num(p['AlphaData'])) if numel(p['AlphaData']) == 1 else 1.0,
                 rgb=bool(a.ndim == 3))
    elif t == 'text':
        d.update(_text_json(c))
    elif t == 'light':
        d.update(position=[float(x) for x in np.asarray(p['Position'], float).reshape(-1)], style=p['Style'], color=_color(p['Color']))
    else:
        # a series
        d['type'] = 'series'
        d['kind'] = c.kind
        for k in ('XData', 'YData', 'ZData', 'CData', 'UData', 'VData', 'SizeData', 'YNegativeDelta', 'YPositiveDelta', 'XNegativeDelta', 'XPositiveDelta'):
            v = p.get(k)
            if v is not None and type(v) is not Char and not isinstance(v, str) and numel(v):
                d[k[0].lower() + k[1:]] = _arr(v)
        d.update(faceColor=_color(p['FaceColor']), edgeColor=_color(p['EdgeColor']), color=_color(p['Color']),
                 lineStyle=p['LineStyle'], lineWidth=float(p['LineWidth']), marker=p['Marker'], markerSize=float(p['MarkerSize']),
                 mfc=_color(p['MarkerFaceColor']), mec=_color(p['MarkerEdgeColor']), faceAlpha=float(_num(p['FaceAlpha']) or 1.0),
                 barWidth=float(p['BarWidth']), baseValue=float(p['BaseValue']), showText=bool(p['ShowText']),
                 fill=bool(p['Fill']), horizontal=bool(p['Horizontal']), capSize=float(p['CapSize']),
                 maxHeadSize=float(p['MaxHeadSize']), labels=p.get('Labels') or [])
        for k, v in c.extra.items():
            if isinstance(v, np.ndarray):
                d[k] = _arr(v)
            elif isinstance(v, (list, str, float, int, bool)) or v is None:
                d[k] = v
    return d


def serialize_axes(ax):
    from .glayout import auto_limits, auto_clim
    p = ax.props
    lims = auto_limits(ax)
    xl = list(p['XLim'].reshape(-1)) if p['XLimMode'] == 'manual' else lims['XLim']
    yl = list(p['YLim'].reshape(-1)) if p['YLimMode'] == 'manual' else lims['YLim']
    zl = list(p['ZLim'].reshape(-1)) if p['ZLimMode'] == 'manual' else lims['ZLim']
    cl = list(p['CLim'].reshape(-1)) if p['CLimMode'] == 'manual' else auto_clim(ax)
    cmap = ax.get_value('Colormap')
    d = {
        'id': ax.id, 'type': 'axes', 'kind': ax.kind,
        'position': [float(x) for x in np.asarray(p['Position'], float).reshape(-1)],
        'xlim': [float(x) for x in xl], 'ylim': [float(x) for x in yl], 'zlim': [float(x) for x in zl],
        'xlimMode': p['XLimMode'], 'ylimMode': p['YLimMode'], 'zlimMode': p['ZLimMode'],
        'clim': [float(x) for x in cl], 'tight': lims.get('tight', {}),
        'xscale': p['XScale'], 'yscale': p['YScale'], 'zscale': p['ZScale'],
        'xdir': p['XDir'], 'ydir': p['YDir'], 'zdir': p['ZDir'],
        'xgrid': bool(p['XGrid']), 'ygrid': bool(p['YGrid']), 'zgrid': bool(p['ZGrid']),
        'xminorgrid': bool(p['XMinorGrid']), 'yminorgrid': bool(p['YMinorGrid']), 'zminorgrid': bool(p['ZMinorGrid']),
        'box': bool(p['Box']), 'color': _color(p['Color']), 'xcolor': _color(p['XColor']), 'ycolor': _color(p['YColor']),
        'zcolor': _color(p['ZColor']), 'gridColor': _color(p['GridColor']), 'gridAlpha': float(p['GridAlpha']),
        'gridLineStyle': p['GridLineStyle'], 'fontSize': float(p['FontSize']), 'lineWidth': float(p['LineWidth']),
        'tickDir': p['TickDir'], 'view': [float(x) for x in p['View'].reshape(-1)],
        'xtick': [float(x) for x in np.asarray(p['XTick'], float).reshape(-1)] if p['XTickMode'] == 'manual' else None,
        'ytick': [float(x) for x in np.asarray(p['YTick'], float).reshape(-1)] if p['YTickMode'] == 'manual' else None,
        'ztick': [float(x) for x in np.asarray(p['ZTick'], float).reshape(-1)] if p['ZTickMode'] == 'manual' else None,
        'xticklabel': p['XTickLabel'] if p['XTickLabelMode'] == 'manual' else None,
        'yticklabel': p['YTickLabel'] if p['YTickLabelMode'] == 'manual' else None,
        'zticklabel': p['ZTickLabel'] if p['ZTickLabelMode'] == 'manual' else None,
        'xtickrot': float(p['XTickLabelRotation']), 'ytickrot': float(p['YTickLabelRotation']),
        'xaxisLocation': p['XAxisLocation'], 'yaxisLocation': p['YAxisLocation'],
        'dar': [float(x) for x in p['DataAspectRatio'].reshape(-1)], 'darMode': p['DataAspectRatioMode'],
        'pbar': [float(x) for x in p['PlotBoxAspectRatio'].reshape(-1)], 'pbarMode': p['PlotBoxAspectRatioMode'],
        'visible': bool(p['Visible']), 'layer': p['Layer'],
        'title': _text_json(ax.title), 'subtitle': _text_json(ax.subtitle), 'xlabel': _text_json(ax.xlabel), 'ylabel': _text_json(ax.ylabel),
        'zlabel': _text_json(ax.zlabel), 'cmap': _b64(np.asarray(cmap, float)),
        'children': [serialize_child(c, ax) for c in reversed(ax.children) if c.valid and not getattr(c, 'hidden', False)],
        'texts': [],
        'yy': None,
        'units': p['Units'], 'fontUnits': p['FontUnits'],
        'parent': ax.parent.id if ax.parent is not None and ax.parent.TYPE not in ('figure', 'axes') else None,
    }
    d.update(_interact_json(ax))
    if ax.yy is not None:
        d['yy'] = {'side': ax.yy['side'], 'right': serialize_axes(ax.yy['right']) if ax.yy.get('right') is not None else None}
    return d


def serialize_figure(f):
    p = f.props
    pos = np.asarray(p['Position'], float).reshape(-1)
    d = {'id': f.id, 'type': 'figure', 'number': int(p['Number']), 'name': p['Name'], 'numberTitle': bool(p['NumberTitle']),
         'width': float(pos[2]), 'height': float(pos[3]), 'color': _color(p['Color']), 'visible': bool(p['Visible']),
         'version': f.version, 'windowStyle': p['WindowStyle'],
         'axes': [], 'legends': [], 'colorbars': [], 'annotations': [], 'sgtitle': None,
         'cmap': _b64(np.asarray(p['Colormap'], float))}
    for c in reversed(f.children):
        if not c.valid:
            continue
        if c.TYPE == 'axes' and c.yy_owner is None:
            d['axes'].append(serialize_axes(c))
        elif c.TYPE == 'legend':
            lp = c.props
            entries = []
            for e in c.entries:
                if not e.valid:
                    continue
                ed = {'id': e.id, 'name': e.props.get('DisplayName', ''), 'type': e.TYPE if e.TYPE != 'series' else 'series'}
                if isinstance(e, Series):
                    ed['kind'] = e.kind
                ep = e.props
                for k in ('Color', 'LineStyle', 'LineWidth', 'Marker', 'MarkerSize', 'MarkerFaceColor', 'MarkerEdgeColor', 'FaceColor', 'EdgeColor', 'FaceAlpha'):
                    if k in ep:
                        v = ep[k]
                        ed[k[0].lower() + k[1:]] = _color(v) if 'Color' in k else (float(_num(v)) if k in ('LineWidth', 'MarkerSize', 'FaceAlpha') and not isinstance(v, str) else v)
                if isinstance(e, Series) and e.kind in ('bar', 'histogram', 'area', 'pie'):
                    fc = e.props['FaceColor']
                    if isinstance(fc, str) and fc in ('flat', 'auto'):
                        ed['faceColor'] = _color(e.extra.get('fc', (0.0, 0.447, 0.741)))
                entries.append(ed)
            d['legends'].append({'id': c.id, 'axes': c.axes.id, 'location': lp['Location'], 'orientation': lp['Orientation'],
                                 'box': bool(lp['Box']), 'fontSize': float(lp['FontSize']), 'visible': bool(lp['Visible']),
                                 'textColor': _color(lp['TextColor']), 'color': _color(lp['Color']), 'edgeColor': _color(lp['EdgeColor']),
                                 'numColumns': int(float(lp['NumColumns'])), 'title': lp['Title'], 'entries': entries,
                                 'interpreter': lp['Interpreter']})
        elif c.TYPE == 'colorbar':
            cp = c.props
            d['colorbars'].append({'id': c.id, 'axes': c.axes.id, 'location': cp['Location'], 'fontSize': float(cp['FontSize']),
                                   'visible': bool(cp['Visible']), 'ticks': [float(x) for x in cp['Ticks'].reshape(-1)] if cp['Ticks'] is not None else None,
                                   'tickLabels': cp['TickLabels'], 'label': _text_json(c.label), 'color': _color(cp['Color']),
                                   'direction': cp['Direction']})
        elif c.TYPE == 'text':
            d['annotations'].append(serialize_child(c, None))
    if getattr(f, 'sgtitle', None) is not None:
        d['sgtitle'] = _text_json(f.sgtitle)
    if f.layout is not None:
        d['layout'] = f.layout
    from .uiobjects import serialize_ui
    serialize_ui(f, d)
    return d


# what a person can click has callbacks; text can size itself to its axes
for _C in (Axes, Line, Surface, Patch, Image, Text, Series):
    _C.DEFAULTS = {**_C.DEFAULTS, **INTERACT}
    _C.ALIASES = {'ContextMenu': 'UIContextMenu'}
Text.DEFAULTS['FontUnits'] = 'points'
Axes.DEFAULTS['FontUnits'] = 'points'
Axes.DEFAULTS['CurrentPoint'] = lambda: np.zeros((2, 3))

# Properties programs of older releases set, kept and shown by get but
# drawing nothing different: DoubleBuffer, EraseMode, DrawMode and the like.
Figure.DEFAULTS.update({'DoubleBuffer': True, 'BackingStore': True, 'MinColormap': 64.0, 'ShareColors': True,
                        'RendererMode': 'auto', 'PaperUnits': 'inches', 'PaperSize': lambda: np.array([[8.5, 11.0]]),
                        'PaperType': 'usletter', 'PaperOrientation': 'portrait', 'Selected': False, 'SelectionHighlight': True,
                        'GraphicsSmoothing': True, 'Alphamap': lambda: np.linspace(0.0, 1.0, 64).reshape(1, -1)})
Axes.DEFAULTS.update({'DrawMode': 'normal', 'ALim': lambda: np.array([[0.0, 1.0]]), 'ALimMode': 'auto', 'MinorGridLineStyle': ':'})
for _C in (Line, Patch, Surface, Image, Text):
    _C.DEFAULTS['EraseMode'] = 'normal'
for _C in (Patch, Surface, Image):
    _C.DEFAULTS.setdefault('Clipping', True)
Line.DEFAULTS['LineSmoothing'] = False
Patch.DEFAULTS.update({'LineSmoothing': False, 'EdgeLighting': 'none'})
Image.DEFAULTS['AlphaDataMapping'] = 'none'
Text.DEFAULTS.update({'LineStyle': '-', 'Editing': False, 'FontSmoothing': True})


def register(*classes):
    """Property names as typed, matched without regard to case; the other
    names some properties go by."""
    for C in classes:
        names = list(C.DEFAULTS) + list(_EXTRA.get(C, ()))
        C._lower = {n.lower(): n for n in names}
        C._alias = {a.lower(): n for a, n in getattr(C, 'ALIASES', {}).items() if n in C.DEFAULTS}


_EXTRA = {Axes: ('Title', 'XLabel', 'YLabel', 'ZLabel', 'Legend'), Colorbar: ('Label',), Text: ('Extent',), Root: ('CallbackObject',)}
register(Root, Figure, Axes, Line, Surface, Patch, Image, Text, Legend, Colorbar, Light, Series)
GObj._lower = {}
GObj._alias = {}
