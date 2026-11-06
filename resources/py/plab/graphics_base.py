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
            # 'pos' begins Position and PositionConstraint: the name the others only extend
            short = [h for h in hits if all(o.lower().startswith(h.lower()) for o in hits)]
            if len(short) == 1:
                return short[0]
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

    SAME_AS = {}          # a property that is another under a second name (a figure's InnerPosition is its Position)
    MODED = ()            # properties with an XxxMode that turns 'manual' when they are set, and back to the default at 'auto'

    def getprop(self, name):
        if not self.valid:
            raise gerr('Invalid or deleted object.', 'MATLAB:class:InvalidHandle')
        if name == 'Parent':
            return self.parent if self.parent is not None else EMPTY()
        if name == 'Children':
            return HArr.of([c for c in self.children if c.valid and not getattr(c, 'hidden', False)], col=True)
        if name == 'Type':
            return Char.of(getattr(self, 'TYPE_NAME', self.TYPE))
        k = self.canon(name)
        if k is None:
            if name.lower() == 'parent':
                return self.getprop('Parent')
            if name.lower() == 'children':
                return self.getprop('Children')
            if name.lower() == 'type':
                return Char.of(getattr(self, 'TYPE_NAME', self.TYPE))
            d = split_default(name)
            if d is not None:
                return self.default_value(*d)
            raise gerr(f"Unrecognized property '{name}' for class '{self.CLASSNAME.split('.')[-1]}'.", 'MATLAB:noSuchMethodOrField')
        return self.get_value(self.SAME_AS.get(k, k))

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
        k = self.SAME_AS.get(k, k)
        self.set_value(k, value)
        if k in self.MODED and k + 'Mode' in self.props:
            self.props[k + 'Mode'] = 'manual'
        self.touch()

    def set_value(self, k, value):
        if k == 'FontUnits':
            from .uiobjects import set_font_units
            set_font_units(self, value)
            return
        if k in _CHOICES and type(value) in (Char, Str):
            v = choice(value, _CHOICES[k])
            if v not in _CHOICES[k]:
                raise gerr(f"Invalid value for {k}: use " + ', '.join(f"'{c}'" for c in _CHOICES[k]) + '.')
            self.props[k] = v
            return
        if k.endswith('Mode') and k[:-4] in self.MODED:
            s = py_str(value).lower() if type(value) in (Char, Str) else ''
            if s not in ('auto', 'manual'):
                raise gerr(f"Invalid value for {k}: use 'auto' or 'manual'.")
            self.props[k] = s
            if s == 'auto':
                d = type(self).DEFAULTS.get(k[:-4])
                self.props[k[:-4]] = d() if callable(d) else d
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
        from .display import all_props_link
        lines.append(all_props_link(self))
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
                'TextBackgroundColor': ('none',), 'TextEdgeColor': ('none',),
                'ForegroundColor': (), 'HighlightColor': (), 'ShadowColor': ()}
_ONOFF = {'Visible', 'Box', 'XGrid', 'YGrid', 'ZGrid', 'XMinorGrid', 'YMinorGrid', 'ZMinorGrid', 'XMinorTick', 'YMinorTick',
          'ZMinorTick', 'Clipping', 'HitTest', 'NumberTitle', 'AutoUpdate', 'Resize', 'ShowText', 'Selected',
          'Interruptible', 'BeingDeleted', 'SelectionHighlight', 'Separator', 'Checked', 'State', 'Enable', 'IntegerHandle',
          'DockControls', 'RowStriping', 'ShowHiddenHandles', 'DoubleBuffer', 'BackingStore', 'ShareColors',
          'GraphicsSmoothing', 'LineSmoothing', 'Editing', 'FontSmoothing', 'FitBoxToText'}


# the values some properties take, one of them (case not minded)
def choice(value, names):
    """A property's text value as one of its names: the name itself (case aside), or the one name it begins
    ('normal' for 'normalized', 'toggle' for 'togglebutton'); otherwise the text as given, lower case, for the caller to refuse."""
    v = py_str(value).lower()
    if v in names or not v:
        return v
    hits = [n for n in names if n.startswith(v)]
    return hits[0] if len(hits) == 1 else v


_CHOICES = {**{f'{a}LimitMethod': ('tickaligned', 'tight', 'padded') for a in 'XYZ'},
            'TitleHorizontalAlignment': ('left', 'center', 'right'), 'LineJoin': ('round', 'miter', 'chamfer'),
            'Interpolation': ('nearest', 'bilinear'), 'AlphaScale': ('linear', 'log'), 'ColorScale': ('linear', 'log'),
            'BoxStyle': ('back', 'full'), 'ClippingStyle': ('3dbox', 'rectangle'), 'AlphaDataMapping': ('none', 'scaled', 'direct'),
            'SubtitleFontWeight': ('normal', 'bold'), 'XDataMode': ('auto', 'manual'), 'YDataMode': ('auto', 'manual'),
            'VertexNormalsMode': ('auto', 'manual'), 'FaceNormalsMode': ('auto', 'manual')}


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
    if k in _ONOFF or isinstance(obj.props.get(k), bool):
        # (and any other property kept as on or off: a bar's Horizontal, a contour's Fill)
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
            # as gcf finds it (a figure whose handle is hidden is not current outside its callbacks), but making none
            from .builtins.graphics import shown_test
            shown = shown_test()
            f = STORE.current
            if f is not None and f.valid and shown(f):
                return f
            rest = sorted((g for g in STORE.figures.values() if g.valid and shown(g)), key=lambda g: -g.order)
            return rest[0] if rest else EMPTY()
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
    SAME_AS = {'InnerPosition': 'Position', 'OuterPosition': 'Position'}
    DEFAULTS = {'Number': 1.0, 'Name': '', 'NumberTitle': True, 'Position': lambda: np.array([[680, 458, 560, 420]], F64),
                'InnerPosition': None, 'OuterPosition': None,
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
        if k == 'WindowStyle':
            s = py_str(value).lower() if isinstance(value, (str, Char, Str)) else None
            if s not in ('normal', 'modal', 'docked', 'alwaysontop'):
                raise gerr("WindowStyle is 'normal', 'modal', 'docked' or 'alwaysontop'.", 'MATLAB:hg:figure:WindowStyle')
            self.props[k] = s
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
            # the newest figure left whose handle is shown (never a dialog's window)
            rest = sorted((f for f in STORE.figures.values() if f.props['HandleVisibility'] == 'on'), key=lambda f: -f.order)
            STORE.current = rest[0] if rest else None

    def axes_list(self):
        return [c for c in self.children if c.valid and c.TYPE == 'axes']

    def display_lines(self):
        p = self.props
        pos = p['Position'].reshape(-1)
        return ['  Figure (' + str(int(p['Number'])) + (': ' + p['Name'] if p['Name'] else '') + ') with properties:', '',
                f"      Number: {int(p['Number'])}", f"        Name: '{p['Name']}'",
                f"       Color: [{' '.join(f'{x:g}' for x in p['Color'])}]",
                f"    Position: [{' '.join(f'{x:g}' for x in pos)}]", "       Units: 'pixels'", '', _all_props_link(self)]


class Axes(GObj):
    TYPE = 'axes'
    CLASSNAME = 'matlab.graphics.axis.Axes'
    SAME_AS = {'InnerPosition': 'Position'}
    MODED = ('FontSize', 'GridAlpha', 'GridColor', 'TickDir', 'XColor', 'YColor', 'ZColor')
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
        'AmbientLightColor': (1.0, 1.0, 1.0), 'XAxis': None, 'YAxis': None, 'ZAxis': None,
        # the inner position is the Position; PositionConstraint is ActivePositionProperty by its newer name; TightInset
        # is estimated from the fonts (axes_tight_inset)
        'InnerPosition': None, 'PositionConstraint': None, 'TightInset': None, 'SubtitleFontWeight': 'normal',
        'TitleHorizontalAlignment': 'center', 'FontAngle': 'normal', 'FontSmoothing': True, 'MinorGridColor': (0.1, 0.1, 0.1),
        'FontSizeMode': 'auto', 'GridAlphaMode': 'auto', 'GridColorMode': 'auto', 'TickDirMode': 'auto',
        'XColorMode': 'auto', 'YColorMode': 'auto', 'ZColorMode': 'auto',
        'XLimitMethod': 'tickaligned', 'YLimitMethod': 'tickaligned', 'ZLimitMethod': 'tickaligned',
        'AlphaScale': 'linear', 'Alphamap': lambda: np.linspace(0, 1, 64).reshape(1, -1), 'ColorScale': 'linear',
        'BoxStyle': 'back', 'ClippingStyle': '3dbox', 'Interactions': lambda: EMPTY(), 'Toolbar': lambda: EMPTY(),
        'CameraViewAngle': 6.6086, 'CameraViewAngleMode': 'auto',
        # where the camera is: along the view's direction from the target (camera_position), so it follows View
        'CameraPosition': lambda: np.array([[0.0, 0.0, 0.0]]), 'CameraPositionMode': 'auto',
        'CameraTarget': lambda: np.array([[0.5, 0.5, 0.5]]), 'CameraTargetMode': 'auto',
        'CameraUpVector': lambda: np.array([[0.0, 0.0, 1.0]]), 'CameraUpVectorMode': 'auto',
        'BubbleSizeRange': lambda: np.array([[1.0, 20.0]]), 'BubbleLim': lambda: np.array([[0.0, 1.0]]), 'BubbleLimMode': 'auto',
        'ZTickLabelRotation': 0.0,
        # polar axes' own
        'RLim': lambda: np.array([[0.0, 1.0]]), 'RLimMode': 'auto', 'RTick': lambda: EMPTY(), 'RTickMode': 'auto',
        'RTickLabel': None, 'RTickLabelMode': 'auto', 'ThetaTick': lambda: np.arange(0.0, 360.0, 30.0).reshape(1, -1),
        'ThetaTickMode': 'auto', 'ThetaTickLabel': None, 'ThetaTickLabelMode': 'auto', 'ThetaDir': 'counterclockwise',
        'ThetaZeroLocation': 'right', 'ThetaAxisUnits': 'degrees',
    }
    SHOWN = ['XLim', 'YLim', 'XScale', 'YScale', 'GridLineStyle', 'Position', 'Units']
    POLAR_ONLY = ('RLim', 'RLimMode', 'RTick', 'RTickMode', 'RTickLabel', 'RTickLabelMode', 'ThetaTick', 'ThetaTickMode',
                  'ThetaTickLabel', 'ThetaTickLabelMode', 'ThetaDir', 'ThetaZeroLocation', 'ThetaAxisUnits')

    def __init__(self, parent, **props):
        super().__init__(parent, **props)
        # new axes start from their figure's alphamap (alphamap sets it)
        f = self.figure()
        if f is not None and 'Alphamap' not in props and f.props.get('Alphamap') is not None:
            self.props['Alphamap'] = np.array(f.props['Alphamap'], float).reshape(1, -1)
        self.title = Text(None, String='', hidden=True)
        self.title.props['FontWeight'] = 'bold'
        self.xlabel = Text(None, String='')
        self.ylabel = Text(None, String='')
        self.zlabel = Text(None, String='')
        self.subtitle = Text(None, String='')
        for t in (self.title, self.xlabel, self.ylabel, self.zlabel, self.subtitle):
            t.parent = self
            t.hidden = True
        # the y and z labels read upwards
        self.ylabel.props['Rotation'] = 90.0
        self.zlabel.props['Rotation'] = 90.0
        self.legend = None
        self.colorbar = None
        self.kind = 'cartesian'        # or 'polar'
        self.yy = None                 # yyaxis: {'side': 'left'|'right', 'right': Axes}
        self.yy_owner = None
        self.layout_cell = None
        self.is3d_hint = False

    @property
    def cls(self):
        if self.kind == 'geo':
            return 'matlab.graphics.axis.GeographicAxes'
        return 'matlab.graphics.axis.PolarAxes' if self.kind == 'polar' else self.CLASSNAME

    # what yyaxis's two sides share: read and set through the right side's axes, they are the left side's
    YY_SHARED = {n.lower() for n in ('Title', 'Subtitle', 'XLabel', 'XLim', 'XLimMode', 'XTick', 'XTickMode', 'XTickLabel',
                                     'XTickLabelMode', 'XScale', 'XDir', 'XGrid', 'XMinorGrid', 'XAxisLocation')}

    # and what belongs to the side yyaxis made active: read and set through either side's axes, they are that side's
    YY_SIDE = {n.lower() for n in ('YLabel', 'YLim', 'YLimMode', 'YTick', 'YTickMode', 'YTickLabel', 'YTickLabelMode',
                                   'YScale', 'YDir', 'YColor')}

    def _yy_active(self):
        """The axes of the side yyaxis last made active (self when it has no two sides)."""
        owner = self.yy_owner if self.yy_owner is not None else self
        if owner.yy is None or owner.yy.get('right') is None:
            return self
        return owner.yy['right'] if owner.yy['side'] == 'right' else owner

    def getprop(self, name):
        if self.yy_owner is not None and name.lower() in self.YY_SHARED:
            return self.yy_owner.getprop(name)
        if name.lower() in self.YY_SIDE and (self.yy is not None or self.yy_owner is not None):
            side = self._yy_active()
            if side is not self:
                return side.getprop(name)
        if name.lower() == 'type' and self.kind in ('polar', 'geo'):
            return Char.of('polaraxes' if self.kind == 'polar' else 'geoaxes')
        if name.lower() == 'basemap' and self.kind == 'geo':
            return Char.of(getattr(self, 'extra_geo', {}).get('basemap', 'none'))
        return super().getprop(name)

    def setprop(self, name, value):
        if self.yy_owner is not None and name.lower() in self.YY_SHARED:
            self.yy_owner.setprop(name, value)
            return
        if name.lower() in self.YY_SIDE and (self.yy is not None or self.yy_owner is not None):
            side = self._yy_active()
            if side is not self:
                side.setprop(name, value)
                return
        if name.lower() == 'basemap' and self.kind == 'geo':
            from .builtins.mapping import set_basemap
            set_basemap(self, value)
            return
        super().setprop(name, value)

    def _set_labels(self, k, value):
        """A tick-label property: its labels as text, and its mode manual."""
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

    def propnames(self):
        names = super().propnames()
        if self.kind != 'polar':
            names = [n for n in names if n not in self.POLAR_ONLY]
        return sorted(names + ['Basemap']) if self.kind == 'geo' else names

    def get_value(self, k):
        if k in ('XLim', 'YLim', 'ZLim') and self.props[k + 'Mode'] == 'auto':
            from .glayout import auto_limits
            lims = auto_limits(self)
            return np.array([lims[k]])
        if k in ('XTick', 'YTick', 'ZTick') and self.props[k + 'Mode'] == 'auto':
            from .glayout import auto_ticks
            return np.array([auto_ticks(self, k[0])]) if True else EMPTY()
        if k in ('XTickLabel', 'YTickLabel', 'ZTickLabel') and self.props[k + 'Mode'] == 'auto':
            from .glayout import auto_ticks, tick_labels, format_tick
            t = auto_ticks(self, k[0])
            fmt = (getattr(self, 'tickfmt', None) or {}).get(k[0])
            labels = [format_tick(fmt, v) for v in t] if fmt else tick_labels(t, self.props[k[0] + 'Scale'])[0]
            return Cell.of_list([Char.of(s) for s in labels], (len(labels), 1))
        if k in ('RLim', 'RTick', 'RTickLabel') and self.props[k + 'Mode'] == 'auto':
            from .glayout import polar_ticks, tick_labels
            ticks, top = polar_ticks(self)
            if k == 'RLim':
                return np.array([[0.0, top]])
            if k == 'RTick':
                return np.array([ticks])
            labels = tick_labels(ticks)[0]
            return Cell.of_list([Char.of(s) for s in labels], (len(labels), 1))
        if k == 'ThetaTickLabel' and self.props[k + 'Mode'] == 'auto':
            t = np.asarray(self.props['ThetaTick'], float).reshape(-1)
            labels = [f'{x:g}°' for x in t]
            return Cell.of_list([Char.of(s) for s in labels], (len(labels), 1))
        if k == 'CLim' and self.props['CLimMode'] == 'auto':
            from .glayout import auto_clim
            return np.array([auto_clim(self)])
        if k == 'BubbleLim':
            return np.array([bubble_lim(self)])
        if k == 'CameraViewAngle' and self.props['CameraViewAngleMode'] == 'auto':
            return self.auto_view_angle()
        if k == 'CameraTarget' and self.props['CameraTargetMode'] == 'auto':
            # the middle of the limits
            return np.array([[float(np.mean(np.asarray(self.get_value(a), float))) for a in ('XLim', 'YLim', 'ZLim')]])
        if k == 'CameraPosition':
            return self.camera_position()
        if k == 'ALim' and self.props.get('ALimMode', 'auto') == 'auto':
            return np.array([auto_alim(self)])
        if k == 'PositionConstraint':
            return Char.of('innerposition' if self.props['ActivePositionProperty'] == 'position' else 'outerposition')
        if k == 'TightInset':
            return axes_tight_inset(self)
        if k == 'Subtitle':
            return self.subtitle
        if k == 'SubtitleFontWeight':
            return Char.of(self.subtitle.props.get('FontWeight', 'normal'))
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
        if k in ('BubbleLim', 'BubbleSizeRange'):
            a = np.asarray(value if type(value) is not float else [value], float).reshape(-1)
            if a.size != 2 or not np.all(np.isfinite(a)) or not (a[0] < a[1] or (k == 'BubbleSizeRange' and a[0] == a[1])) \
                    or (k == 'BubbleSizeRange' and a[0] <= 0):
                what = 'positive and increasing' if k == 'BubbleSizeRange' else 'increasing'
                raise gerr(f'Value must be a 1x2 vector of finite numbers, {what}.', 'MATLAB:hg:shaped_arrays:LimitsPredicate')
            self.props[k] = np.array([[float(a[0]), float(a[1])]])
            if k == 'BubbleLim':
                self.props['BubbleLimMode'] = 'manual'
            return
        if k == 'RLim':
            a = np.asarray(value if type(value) is not float else [value], float).reshape(-1)
            if a.size != 2 or not a[0] < a[1]:
                raise gerr('Value must be a 1x2 vector of numeric type in which the second element is larger than the first.', 'MATLAB:hg:shaped_arrays:LimitsPredicate')
            self.props['RLim'] = a.reshape(1, 2)
            self.props['RLimMode'] = 'manual'
            return
        if k in ('RTick', 'ThetaTick'):
            a = np.asarray(value, float).reshape(1, -1) if numel(value) else np.zeros((1, 0))
            self.props[k] = a
            self.props[k + 'Mode'] = 'manual'
            return
        if k in ('RTickLabel', 'ThetaTickLabel'):
            return self._set_labels(k, value)
        if k in ('XLim', 'YLim', 'ZLim', 'CLim', 'ALim'):
            a = np.asarray(value if type(value) is not float else [value], float).reshape(-1)
            if a.size != 2:
                raise gerr('Value must be a 1x2 vector of numeric type in which the second element is larger than the first and may be Inf.', 'MATLAB:hg:shaped_arrays:LimitsWithInfsPredicate')
            lo, hi = float(a[0]), float(a[1])
            if not lo < hi:
                raise gerr('Value must be a 1x2 vector of numeric type in which the second element is larger than the first and may be Inf.', 'MATLAB:hg:shaped_arrays:LimitsWithInfsPredicate')
            if math.isinf(lo) or math.isinf(hi):
                from .glayout import auto_limits, auto_clim
                auto = auto_clim(self) if k == 'CLim' else auto_alim(self) if k == 'ALim' else auto_limits(self)[k]
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
            return self._set_labels(k, value)
        if k == 'CameraViewAngle':
            a = np.asarray(value, float).reshape(-1) if not isinstance(value, (Char, Str)) else np.zeros(0)
            if a.size != 1 or not 0 <= a[0] < 180:
                raise gerr('Value must be a scalar greater than or equal to 0 and less than 180.')
            self.props[k] = float(a[0])
            self.props[k + 'Mode'] = 'manual'
            return
        if k == 'CameraPosition':
            # the view turned to look from there toward the target, and the distance kept, so that it reads back as set
            a = np.asarray(value, float).reshape(-1) if not isinstance(value, (Char, Str)) else np.zeros(0)
            if a.size != 3 or not np.all(np.isfinite(a)):
                raise gerr('Value must be a vector of three finite numbers.')
            d = a - np.asarray(self.get_value('CameraTarget'), float).reshape(-1)
            dist = float(np.linalg.norm(d))
            if dist == 0:
                raise gerr('The camera position cannot be the camera target.')
            self.props['View'] = np.array([[math.degrees(math.atan2(d[0], -d[1])), math.degrees(math.atan2(d[2], math.hypot(d[0], d[1])))]])
            self.cam_dist = dist
            # the point as given while the view and the target stay as they are (the angles' round trip adds noise)
            self.cam_set = (a.reshape(1, 3).copy(), self.props['View'].copy(), np.asarray(self.get_value('CameraTarget'), float).reshape(-1).copy())
            self.props['CameraPositionMode'] = 'manual'
            self.touch()
            return
        if k in ('CameraTarget', 'CameraUpVector'):
            a = np.asarray(value, float).reshape(-1) if not isinstance(value, (Char, Str)) else np.zeros(0)
            if a.size != 3 or not np.all(np.isfinite(a)) or (k == 'CameraUpVector' and not np.any(a)):
                raise gerr('Value must be a vector of three finite numbers' + (', not all zero.' if k == 'CameraUpVector' else '.'))
            self.props[k] = a.reshape(1, 3)
            self.props[k + 'Mode'] = 'manual'
            self.touch()
            return
        if k in ('XLimMode', 'YLimMode', 'ZLimMode', 'XTickMode', 'YTickMode', 'ZTickMode', 'CLimMode', 'ALimMode',
                 'XTickLabelMode', 'YTickLabelMode', 'ZTickLabelMode', 'DataAspectRatioMode', 'PlotBoxAspectRatioMode',
                 'CameraViewAngleMode', 'CameraTargetMode', 'CameraUpVectorMode', 'CameraPositionMode', 'RLimMode', 'RTickMode', 'ThetaTickMode',
                 'RTickLabelMode', 'ThetaTickLabelMode'):
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
        if k == 'PositionConstraint':
            s = py_str(value).lower() if type(value) in (Char, Str) else ''
            if s not in ('innerposition', 'outerposition'):
                raise gerr("Invalid value for PositionConstraint: use 'innerposition' or 'outerposition'.")
            self.props['ActivePositionProperty'] = 'position' if s == 'innerposition' else 'outerposition'
            return
        if k == 'TightInset':
            raise gerr('You cannot set the read-only property TightInset of Axes.', 'MATLAB:class:SetProhibited')
        if k == 'SubtitleFontWeight':
            super().set_value(k, value)
            self.subtitle.props['FontWeight'] = self.props[k]
            return
        if k in ('Title', 'Subtitle', 'XLabel', 'YLabel', 'ZLabel'):
            t = {'Title': self.title, 'Subtitle': self.subtitle, 'XLabel': self.xlabel, 'YLabel': self.ylabel, 'ZLabel': self.zlabel}[k]
            if isinstance(value, Text):
                t.props.update(value.props)
            else:
                t.set_value('String', value)
            return
        if k == 'TitleFontWeight':
            super().set_value(k, value)
            self.title.props['FontWeight'] = self.props[k]
            return
        if k == 'FontSize':
            # the title and labels follow, unless given a size of their own
            old = self.props.get('FontSize')
            super().set_value(k, value)
            for t in (self.title, self.subtitle, self.xlabel, self.ylabel, self.zlabel):
                if t.props.get('FontSize') == old:
                    t.props['FontSize'] = self.props[k]
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
        return [c for c in drawn_children(self) if c.valid and c.TYPE not in ('text', 'light') and not getattr(c, 'hidden', False)]

    def is3d(self):
        v = self.props['View'].reshape(-1)
        return not (abs(v[1]) == 90 and v[0] % 90 == 0 and abs(v[1]) == 90) or self.kind == '3d'

    def camera_position(self):
        """Where the camera is: from the target along the view's azimuth and elevation, ten times the axes' size away
        unless a position was set (then as far as it was), so that it follows the view as it turns."""
        az, el = (math.radians(float(x)) for x in np.asarray(self.props['View'], float).reshape(-1)[:2])
        d = np.array([math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)])
        t = np.asarray(self.get_value('CameraTarget'), float).reshape(-1)
        manual = self.props['CameraPositionMode'] == 'manual'
        kept = getattr(self, 'cam_set', None)
        if manual and kept is not None and np.array_equal(kept[1], self.props['View']) and np.array_equal(kept[2], t):
            return kept[0].copy()
        dist = getattr(self, 'cam_dist', None) if manual else None
        if not dist:
            lims = np.concatenate([np.asarray(self.get_value(k), float).reshape(-1) for k in ('XLim', 'YLim', 'ZLim')])
            dist = 10 * max(float(np.ptp(lims)), 1.0)
        return (t + dist * d).reshape(1, 3)

    def auto_view_angle(self):
        """The camera's angle when the axes fill their place: a view from
        above, or the wider one of a 3-D view."""
        return 10.3396 if self.is3d() else 6.6086

    def camera_zoom(self):
        """How much larger a CameraViewAngle smaller than the automatic one
        draws the axes (about their middle; they may then go past their
        Position, as far as their figure or panel)."""
        if self.props['CameraViewAngleMode'] != 'manual':
            return 1.0
        a = max(float(self.props['CameraViewAngle']), 1e-6)
        return math.tan(math.radians(self.auto_view_angle()) / 2) / math.tan(math.radians(a) / 2)

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
                'Tag': '', 'UserData': lambda: EMPTY(), 'Clipping': True, 'SeriesIndex': 1.0, 'AlignVertexCenters': False,
                'LineJoin': 'round', 'ColorMode': 'auto', 'LineStyleMode': 'auto', 'MarkerMode': 'auto', 'XDataMode': 'manual'}
    SHOWN = ['Color', 'LineStyle', 'LineWidth', 'Marker', 'MarkerSize', 'MarkerFaceColor', 'XData', 'YData', 'ZData']
    MODED = ('Color', 'LineStyle', 'Marker')

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
                'AmbientStrength': 0.3, 'DiffuseStrength': 0.6, 'SpecularStrength': 0.9, 'SpecularExponent': 10.0,
                'SpecularColorReflectance': 1.0, 'BackFaceLighting': 'reverselit',
                'AlphaData': 1.0, 'AlphaDataMapping': 'scaled', 'CDataMode': 'auto', 'CDataSource': '', 'MarkerEdgeColor': 'auto',
                'MarkerFaceColor': 'none', 'XDataMode': 'manual', 'YDataMode': 'manual',
                # computed from the data while their modes are 'auto' (surface_normals)
                'VertexNormals': None, 'VertexNormalsMode': 'auto', 'FaceNormals': None, 'FaceNormalsMode': 'auto'}
    SHOWN = ['EdgeColor', 'LineStyle', 'FaceColor', 'FaceLighting', 'FaceAlpha', 'XData', 'YData', 'ZData', 'CData']
    MODED = ('CData',)

    def get_value(self, k):
        if k in ('VertexNormals', 'FaceNormals') and self.props[k + 'Mode'] == 'auto':
            return surface_normals(self, k == 'FaceNormals')
        return super().get_value(k)

    def set_value(self, k, value):
        if k in ('FaceAlpha', 'EdgeAlpha') and type(value) in (Char, Str):
            self.props[k] = py_str(value)
            return
        if k in ('VertexNormals', 'FaceNormals'):
            self.props[k] = np.asarray(value, float)
            self.props[k + 'Mode'] = 'manual'
            return
        super().set_value(k, value)


class Patch(GObj):
    TYPE = 'patch'
    CLASSNAME = 'matlab.graphics.primitive.Patch'
    DEFAULTS = {'XData': lambda: EMPTY(), 'YData': lambda: EMPTY(), 'ZData': lambda: EMPTY(), 'Faces': lambda: EMPTY(),
                'Vertices': lambda: EMPTY(), 'FaceColor': (0.0, 0.0, 0.0), 'EdgeColor': (0.0, 0.0, 0.0), 'FaceAlpha': 1.0,
                'EdgeAlpha': 1.0, 'LineStyle': '-', 'LineWidth': 0.5, 'CData': lambda: EMPTY(), 'FaceVertexCData': lambda: EMPTY(),
                'Marker': 'none', 'MarkerSize': 6.0, 'MarkerFaceColor': 'none', 'DisplayName': '', 'Visible': True, 'Tag': '',
                'UserData': lambda: EMPTY(), 'FaceLighting': 'flat', 'CDataMapping': 'scaled',
                # how a lit face reflects (set by material too), as a surface has them
                'AmbientStrength': 0.3, 'DiffuseStrength': 0.6, 'SpecularStrength': 0.9, 'SpecularExponent': 10.0,
                'SpecularColorReflectance': 1.0, 'BackFaceLighting': 'reverselit',
                'AlignVertexCenters': False, 'AlphaDataMapping': 'scaled', 'FaceVertexAlphaData': lambda: EMPTY(), 'LineJoin': 'miter',
                'MarkerEdgeColor': 'auto',
                # computed from the faces while their modes are 'auto' (patch_normals); isonormals sets VertexNormals
                'VertexNormals': None, 'VertexNormalsMode': 'auto', 'FaceNormals': None, 'FaceNormalsMode': 'auto'}
    SHOWN = ['FaceColor', 'FaceAlpha', 'EdgeColor', 'LineStyle', 'Faces', 'Vertices']

    def get_value(self, k):
        if k in ('VertexNormals', 'FaceNormals') and self.props.get(k + 'Mode', 'auto') == 'auto':
            return patch_normals(self, k == 'FaceNormals')
        return super().get_value(k)

    def set_value(self, k, value):
        if k in ('VertexNormals', 'FaceNormals'):
            self.props[k] = np.asarray(value, float)
            self.props[k + 'Mode'] = 'manual'
            return
        super().set_value(k, value)


class Polygon(Patch):
    """A polyshape's plot: its boundaries as rings parted by NaN in XData and
    YData, filled even-odd so that holes stay open. Drawn as a patch (TYPE),
    its Type is 'polygon'; setting Shape draws the new polyshape."""
    TYPE_NAME = 'polygon'
    CLASSNAME = 'matlab.graphics.primitive.Polygon'
    OWN_DEFAULTS = {'Shape': lambda: EMPTY(), 'FaceAlpha': 0.35, 'HoleEdgeColor': (0.0, 0.0, 0.0), 'HoleEdgeAlpha': 1.0}
    DEFAULTS = dict(Patch.DEFAULTS, **OWN_DEFAULTS)          # made again from the patch's once those are complete
    SHOWN = ['FaceColor', 'FaceAlpha', 'EdgeColor', 'LineWidth', 'LineStyle', 'Shape']
    rings = True

    def set_value(self, k, value):
        if k == 'Shape':
            if type(value).__name__ != 'PolyShape':
                raise gerr('Shape is a polyshape.', 'MATLAB:hg:polygon:Shape')
            self.props['Shape'] = value
            V = value.vertices()
            self.props['XData'] = V[:, :1].copy() if V.size else EMPTY()
            self.props['YData'] = V[:, 1:].copy() if V.size else EMPTY()
            return
        super().set_value(k, value)

    def get_value(self, k):
        if k == 'Shape':
            return self.props.get('Shape')
        return super().get_value(k)


class Rectangle(Patch):
    """rectangle: a box at Position [x y w h] with its corners rounded by
    Curvature [cx cy] (fractions of the half width and half height; 1 makes
    an ellipse), drawn as a patch of its outline (TYPE), its Type 'rectangle'."""
    TYPE_NAME = 'rectangle'
    CLASSNAME = 'matlab.graphics.primitive.Rectangle'
    OWN_DEFAULTS = {'Position': lambda: np.array([[0.0, 0.0, 1.0, 1.0]]), 'Curvature': lambda: np.array([[0.0, 0.0]]),
                    'FaceColor': 'none', 'EdgeColor': (0.0, 0.0, 0.0)}
    DEFAULTS = dict(Patch.DEFAULTS, **OWN_DEFAULTS)
    SHOWN = ['FaceColor', 'EdgeColor', 'LineWidth', 'LineStyle', 'Curvature', 'Position']

    def set_value(self, k, value):
        if k == 'Position':
            a = np.asarray(value, float).reshape(-1) if not isinstance(value, (Char, Str)) else np.zeros(0)
            if a.size != 4 or a[2] < 0 or a[3] < 0 or not np.all(np.isfinite(a)):
                raise gerr('Position is [x y width height], the width and height not negative.', 'MATLAB:hg:rectangle:Position')
            self.props['Position'] = a.reshape(1, 4)
            self.outline()
            return
        if k == 'Curvature':
            a = np.asarray(value, float).reshape(-1) if not isinstance(value, (Char, Str)) else np.zeros(0)
            if a.size == 1:
                a = np.array([a[0], a[0]])
            if a.size != 2 or np.any(a < 0) or np.any(a > 1):
                raise gerr('Curvature is a number or [horizontal vertical], each from 0 to 1.', 'MATLAB:hg:rectangle:Curvature')
            self.props['Curvature'] = a.reshape(1, 2)
            self.outline()
            return
        super().set_value(k, value)

    def outline(self):
        x, y, w, h = (float(v) for v in np.asarray(self.props['Position'], float).reshape(-1))
        cx, cy = (float(v) for v in np.asarray(self.props['Curvature'], float).reshape(-1))
        rx, ry = cx * w / 2, cy * h / 2
        if rx <= 0 or ry <= 0:
            px = [x, x + w, x + w, x]
            py = [y, y, y + h, y + h]
        else:
            t = np.linspace(0, np.pi / 2, 17)
            px, py = [], []
            for (ox, oy, a0) in ((x + w - rx, y + ry, -np.pi / 2), (x + w - rx, y + h - ry, 0.0),
                                 (x + rx, y + h - ry, np.pi / 2), (x + rx, y + ry, np.pi)):
                px += list(ox + rx * np.cos(a0 + t))
                py += list(oy + ry * np.sin(a0 + t))
        self.props['XData'] = np.asarray(px, float).reshape(-1, 1)
        self.props['YData'] = np.asarray(py, float).reshape(-1, 1)


class Group(GObj):
    """hggroup: objects gathered to be set, shown and hidden together."""
    TYPE = 'hggroup'
    CLASSNAME = 'matlab.graphics.primitive.Group'
    DEFAULTS = {'Visible': True, 'Tag': '', 'UserData': lambda: EMPTY(), 'DisplayName': '', 'Clipping': True}
    SHOWN = ['Children', 'Visible']


class Transform(Group):
    """hgtransform: a group whose children are drawn through Matrix, a 4-by-4
    transform of [x; y; z; 1] (makehgtform makes them)."""
    TYPE = 'hgtransform'
    CLASSNAME = 'matlab.graphics.primitive.Transform'
    DEFAULTS = dict(Group.DEFAULTS, Matrix=lambda: np.eye(4))
    SHOWN = ['Children', 'Visible', 'Matrix']

    def set_value(self, k, value):
        if k == 'Matrix':
            a = np.asarray(value, float) if not isinstance(value, (Char, Str)) else np.zeros(0)
            if a.shape != (4, 4) or not np.all(np.isfinite(a)):
                raise gerr('Matrix is a 4-by-4 transform of finite numbers.', 'MATLAB:hg:hgtransform:Matrix')
            self.props['Matrix'] = a.copy()
            return
        super().set_value(k, value)


def drawn_children(parent, M=None):
    """The children of axes (or of a group) as they are drawn, in order:
    groups opened in place, and under an hgtransform copies of the objects
    with its matrix applied to their data."""
    res = []
    for c in parent.children:
        if not c.valid:
            continue
        if isinstance(c, Group):
            if not c.props.get('Visible', True):
                continue
            Mc = M
            if isinstance(c, Transform):
                T = np.asarray(c.props['Matrix'], float)
                Mc = T if M is None else M @ T
            res += drawn_children(c, Mc)
        else:
            res.append(c if M is None else _transformed(c, M))
    return res


def _apply(M, x, y, z):
    P = np.vstack([x.reshape(-1), y.reshape(-1), z.reshape(-1), np.ones(x.size)])
    Q = M @ P
    w = np.where(Q[3] != 0, Q[3], 1.0)
    return (Q[0] / w).reshape(x.shape), (Q[1] / w).reshape(x.shape), (Q[2] / w).reshape(x.shape)


def _transformed(c, M):
    """A copy of a line, surface, patch or text with M applied (the object itself for anything else)."""
    import copy
    t = c.TYPE
    if t not in ('line', 'surface', 'patch', 'text'):
        return c
    o = copy.copy(c)
    o.props = dict(c.props)
    p = o.props
    if t == 'text':
        pos = np.asarray(p['Position'], float).reshape(-1)
        pos = np.concatenate([pos, np.zeros(3 - pos.size)]) if pos.size < 3 else pos[:3]
        x, y, z = _apply(M, pos[:1], pos[1:2], pos[2:3])
        p['Position'] = np.array([[x[0], y[0], z[0]]])
        return o
    if t == 'patch' and numel(p.get('Vertices')):
        V = np.asarray(p['Vertices'], float)
        z = V[:, 2] if V.shape[1] > 2 else np.zeros(V.shape[0])
        x, y, z = _apply(M, V[:, 0], V[:, 1], z)
        p['Vertices'] = np.column_stack([x, y, z])
        return o
    X = np.asarray(p['XData'], float)
    Y = np.asarray(p['YData'], float)
    Z = np.asarray(p['ZData'], float) if numel(p['ZData']) else None
    if t == 'surface' and Z is not None:
        if X.size != Z.size:
            X, Y = np.meshgrid(X.reshape(-1), Y.reshape(-1))
    z0 = Z if Z is not None else np.zeros(X.shape)
    x, y, z = _apply(M, X, Y, z0)
    p['XData'], p['YData'] = x, y
    if Z is not None or np.any(np.abs(z) > 0):
        p['ZData'] = z
    return o


class Image(GObj):
    TYPE = 'image'
    CLASSNAME = 'matlab.graphics.primitive.Image'
    DEFAULTS = {'CData': lambda: EMPTY(), 'XData': lambda: np.array([[1.0, 1.0]]), 'YData': lambda: np.array([[1.0, 1.0]]),
                'CDataMapping': 'direct', 'AlphaData': 1.0, 'Visible': True, 'Tag': '', 'UserData': lambda: EMPTY(), 'DisplayName': '',
                'Interpolation': 'nearest'}
    SHOWN = ['CData', 'CDataMapping']


def string_value(value):
    """A String property as kept: one line, or a list of lines."""
    if type(value) is Cell:
        return [py_str(x) if type(x) in (Char, Str) else _num_label(x) for x in value.a.reshape(-1, order='F')]
    if type(value) is Char:
        return value.row_strs() if value.a.shape[0] > 1 else value.str()
    if type(value) is Str:
        return [s or '' for s in value.a.reshape(-1, order='F')] if value.a.size != 1 else (value.a.flat[0] or '')
    if type(value) in (float, np.ndarray, bool):
        return ' '.join(_num_label(x) for x in np.asarray(value).reshape(-1)) if numel(value) else ''
    return str(value)


def string_get(v):
    return Cell.of_list([Char.of(s) for s in v], (len(v), 1)) if isinstance(v, list) else Char.of(v)


class Text(GObj):
    TYPE = 'text'
    CLASSNAME = 'matlab.graphics.primitive.Text'
    DEFAULTS = {'String': '', 'Position': lambda: np.array([[0.0, 0.0, 0.0]]), 'FontSize': 10.0, 'FontName': 'Helvetica',
                'FontWeight': 'normal', 'FontAngle': 'normal', 'Color': (0.0, 0.0, 0.0), 'HorizontalAlignment': 'left',
                'VerticalAlignment': 'middle', 'Rotation': 0.0, 'Interpreter': 'tex', 'BackgroundColor': 'none',
                'EdgeColor': 'none', 'LineWidth': 0.5, 'Margin': 3.0, 'Visible': True, 'Units': 'data', 'Tag': '',
                'UserData': lambda: EMPTY(), 'Clipping': False, 'Extent': None}
    SHOWN = ['String', 'FontSize', 'FontWeight', 'FontName', 'Color', 'HorizontalAlignment', 'Position', 'Units']

    def __init__(self, parent=None, **props):
        hidden = props.pop('hidden', False)
        super().__init__(parent, **props)
        self.hidden = hidden

    def set_value(self, k, value):
        if k == 'Extent':
            raise gerr('You cannot set the read-only property Extent of Text.', 'MATLAB:class:SetProhibited')
        if k == 'String':
            self.props[k] = string_value(value)
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
        if k == 'Extent':
            return text_extent(self)
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


# ---- annotations ------------------------------------------------------------------------

HEAD_STYLES = ('none', 'plain', 'ellipse', 'vback1', 'vback2', 'vback3', 'cback1', 'cback2', 'cback3', 'fourstar', 'rectangle',
               'diamond', 'rose', 'hypocycloid', 'astroid', 'deltoid')


class Shape(GObj):
    """annotation(...): a line, arrow, double arrow or text arrow, whose ends X
    and Y are in the figure's normalized units, or a rectangle, ellipse or
    text box at Position [x y w h]. For the line kinds Position is
    [x1 y1 x2-x1 y2-y1], and X, Y and Position are kept in step. Like the
    language's annotations, they are not among the figure's Children."""
    TYPE = 'shape'
    KIND = None
    LINEAR = False
    BASE = {'Units': 'normalized', 'Visible': True, 'Tag': '', 'UserData': lambda: EMPTY(), 'HandleVisibility': 'on',
            'Selected': False, 'BeingDeleted': False, 'CreateFcn': '', 'DeleteFcn': ''}

    def __init__(self, parent=None, **props):
        super().__init__(parent, **props)
        self.hidden = True

    def set_value(self, k, value):
        if k in ('X', 'Y') and self.LINEAR:
            a = np.asarray(value, float).reshape(-1) if numel(value) else np.zeros(0)
            if a.size != 2 or not np.all(np.isfinite(a)):
                raise gerr(f'{k} must be a vector of two numbers: the two ends.', 'MATLAB:annotation:BadXY')
            self.props[k] = a.reshape(1, 2)
            x, y = self.props['X'].reshape(-1), self.props['Y'].reshape(-1)
            self.props['Position'] = np.array([[x[0], y[0], x[1] - x[0], y[1] - y[0]]])
            return
        if k == 'Position':
            a = np.asarray(value, float).reshape(-1) if numel(value) else np.zeros(0)
            if a.size != 4 or not np.all(np.isfinite(a)):
                raise gerr('Position must be a vector of four numbers.', 'MATLAB:annotation:BadPosition')
            self.props[k] = a.reshape(1, 4)
            if self.LINEAR:
                self.props['X'] = np.array([[a[0], a[0] + a[2]]])
                self.props['Y'] = np.array([[a[1], a[1] + a[3]]])
            return
        if k == 'String':
            self.props[k] = string_value(value)
            return
        if k.endswith('Style') and k != 'LineStyle':
            s = py_str(value).lower() if type(value) in (Char, Str) else ''
            if s not in HEAD_STYLES:
                raise gerr(f"{k} must be one of: {', '.join(HEAD_STYLES)}.", 'MATLAB:annotation:BadHeadStyle')
            self.props[k] = s
            return
        super().set_value(k, value)

    def get_value(self, k):
        if k == 'String':
            return string_get(self.props.get('String', ''))
        return super().get_value(k)

    def serialize(self):
        """What the page draws: the kind, where, and how."""
        p = self.props
        d = {'id': self.id, 'shape': self.KIND, 'units': p['Units'], 'visible': bool(p['Visible']), 'color': _color(p['Color']),
             'lineStyle': p['LineStyle'], 'lineWidth': float(p['LineWidth']),
             'position': [float(v) for v in np.asarray(p['Position'], float).reshape(-1)]}
        if self.LINEAR:
            d['x'] = [float(v) for v in p['X'].reshape(-1)]
            d['y'] = [float(v) for v in p['Y'].reshape(-1)]
        head = lambda s: {'style': p[s + 'Style'], 'length': float(p[s + 'Length']), 'width': float(p[s + 'Width'])}  # noqa: E731
        if 'HeadStyle' in p:
            d['head2'] = head('Head')
        if 'Head1Style' in p:
            d['head1'], d['head2'] = head('Head1'), head('Head2')
        if 'FaceColor' in p:
            d['faceColor'] = _color(p['FaceColor'])
        if 'FaceAlpha' in p:
            d['faceAlpha'] = float(p['FaceAlpha'])
        if 'String' in p:
            s = p['String']
            d.update(string=s if isinstance(s, list) else str(s), fontSize=float(p['FontSize']), fontName=p['FontName'],
                     fontWeight=p['FontWeight'], fontAngle=p['FontAngle'], interpreter=p['Interpreter'],
                     halign=p['HorizontalAlignment'], valign=p['VerticalAlignment'])
        if 'TextColor' in p:
            d.update(textColor=_color(p['TextColor']), textBackground=_color(p['TextBackgroundColor']), textEdge=_color(p['TextEdgeColor']),
                     textLineWidth=float(p['TextLineWidth']), textMargin=float(p['TextMargin']), textRotation=float(p['TextRotation']))
        if 'EdgeColor' in p:
            d.update(edgeColor=_color(p['EdgeColor']), background=_color(p['BackgroundColor']), margin=float(p['Margin']),
                     fitBox=bool(p['FitBoxToText']))
        return d


_LINE_SHAPE = {'X': lambda: np.array([[0.3, 0.4]]), 'Y': lambda: np.array([[0.3, 0.4]]), 'Position': lambda: np.array([[0.3, 0.3, 0.1, 0.1]]),
               'Color': (0.0, 0.0, 0.0), 'LineStyle': '-', 'LineWidth': 0.5}
_TEXT_SHAPE = {'String': '', 'FontName': 'Helvetica', 'FontSize': 10.0, 'FontWeight': 'normal', 'FontAngle': 'normal', 'Interpreter': 'tex'}


class LineShape(Shape):
    TYPE, KIND, LINEAR, CLASSNAME = 'lineshape', 'line', True, 'matlab.graphics.shape.Line'
    DEFAULTS = {**_LINE_SHAPE, **Shape.BASE}


class ArrowShape(Shape):
    TYPE, KIND, LINEAR, CLASSNAME = 'arrowshape', 'arrow', True, 'matlab.graphics.shape.Arrow'
    DEFAULTS = {**_LINE_SHAPE, 'HeadStyle': 'vback2', 'HeadLength': 10.0, 'HeadWidth': 10.0, **Shape.BASE}


class DoubleArrowShape(Shape):
    TYPE, KIND, LINEAR, CLASSNAME = 'doubleendarrowshape', 'doublearrow', True, 'matlab.graphics.shape.DoubleEndArrow'
    DEFAULTS = {**_LINE_SHAPE, 'Head1Style': 'vback2', 'Head1Length': 10.0, 'Head1Width': 10.0, 'Head2Style': 'vback2',
                'Head2Length': 10.0, 'Head2Width': 10.0, **Shape.BASE}


class TextArrowShape(Shape):
    TYPE, KIND, LINEAR, CLASSNAME = 'textarrowshape', 'textarrow', True, 'matlab.graphics.shape.TextArrow'
    DEFAULTS = {**_LINE_SHAPE, 'HeadStyle': 'vback2', 'HeadLength': 10.0, 'HeadWidth': 10.0, **_TEXT_SHAPE,
                'TextColor': (0.0, 0.0, 0.0), 'TextBackgroundColor': 'none', 'TextEdgeColor': 'none', 'TextLineWidth': 0.5,
                'TextMargin': 2.0, 'TextRotation': 0.0, 'HorizontalAlignment': 'center', 'VerticalAlignment': 'middle', **Shape.BASE}


class RectangleShape(Shape):
    TYPE, KIND, CLASSNAME = 'rectangleshape', 'rectangle', 'matlab.graphics.shape.Rectangle'
    DEFAULTS = {'Position': lambda: np.array([[0.3, 0.3, 0.1, 0.1]]), 'Color': (0.0, 0.0, 0.0), 'LineStyle': '-', 'LineWidth': 0.5,
                'FaceColor': 'none', 'FaceAlpha': 1.0, **Shape.BASE}


class EllipseShape(RectangleShape):
    TYPE, KIND, CLASSNAME = 'ellipseshape', 'ellipse', 'matlab.graphics.shape.Ellipse'


class TextBoxShape(Shape):
    TYPE, KIND, CLASSNAME = 'textboxshape', 'textbox', 'matlab.graphics.shape.TextBox'
    DEFAULTS = {'Position': lambda: np.array([[0.3, 0.3, 0.1, 0.1]]), **_TEXT_SHAPE, 'FitBoxToText': False, 'Color': (0.0, 0.0, 0.0),
                'BackgroundColor': 'none', 'EdgeColor': (0.0, 0.0, 0.0), 'FaceAlpha': 1.0, 'LineStyle': '-', 'LineWidth': 0.5,
                'HorizontalAlignment': 'left', 'VerticalAlignment': 'top', 'Margin': 5.0, **Shape.BASE}


SHAPES = {C.KIND: C for C in (LineShape, ArrowShape, DoubleArrowShape, TextArrowShape, RectangleShape, EllipseShape, TextBoxShape)}


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
                'MarkerEdgeColor': 'flat', 'FaceAlpha': 1.0, 'EdgeAlpha': 1.0, 'MarkerFaceAlpha': 1.0, 'MarkerEdgeAlpha': 1.0, 'BarWidth': 0.8,
                'BaseValue': 0.0, 'DisplayName': '', 'Visible': True, 'Tag': '', 'UserData': lambda: EMPTY(),
                'SizeData': 36.0, 'LevelList': lambda: EMPTY(), 'LevelListMode': 'auto', 'ShowText': False, 'Fill': False,
                'BinEdges': lambda: EMPTY(), 'Values': lambda: EMPTY(), 'Normalization': 'count', 'NumBins': 0.0,
                'BinWidth': 0.0, 'AutoScaleFactor': 0.9, 'Horizontal': False, 'Labels': lambda: [], 'MaxHeadSize': 0.2,
                'YNegativeDelta': lambda: EMPTY(), 'YPositiveDelta': lambda: EMPTY(), 'XNegativeDelta': lambda: EMPTY(), 'XPositiveDelta': lambda: EMPTY(),
                'CapSize': 6.0, 'Stacked': False}

    CLASSNAMES = {'bar': 'matlab.graphics.chart.primitive.Bar', 'stem': 'matlab.graphics.chart.primitive.Stem',
                  'stair': 'matlab.graphics.chart.primitive.Stair', 'area': 'matlab.graphics.chart.primitive.Area',
                  'errorbar': 'matlab.graphics.chart.primitive.ErrorBar', 'scatter': 'matlab.graphics.chart.primitive.Scatter',
                  'bubblechart': 'matlab.graphics.chart.primitive.BubbleChart',
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
        if k == 'CData' and self.kind in ('scatter', 'bubblechart') and not numel(self.props['CData']) \
                and isinstance(self.props['Color'], tuple):
            return np.array([self.props['Color']], float)
        if k == 'Values' and self.kind == 'histogram':
            return self.extra.get('values', EMPTY())
        if k == 'BinEdges' and self.kind == 'histogram':
            return self.extra.get('edges', EMPTY())
        return super().get_value(k)

    # kind -> (the properties that shape it, fn(series)): what is drawn worked out again
    # when one of them changes (bars and areas laid out, contour lines traced); set by graphics.py
    RELAYOUT = {}

    def set_value(self, k, value):
        self._store(k, value)
        if k == 'LevelList':
            self.props['LevelListMode'] = 'manual'
        r = Series.RELAYOUT.get(self.kind)
        if r is not None and k in r[0] and getattr(self, 'extra', None) is not None:
            r[1](self)

    def _store(self, k, value):
        if k == 'CData' and self.kind in ('scatter', 'bubblechart') and type(value) not in (Char, Str) and numel(value) == 3 \
                and numel(self.props['XData']) != 3:
            # one colour for all the markers
            self.props['Color'] = to_color(value)
            self.props['CData'] = EMPTY()
            self.extra.pop('rgb', None)
            return
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
        if all(getattr(h, 'enum', None) is not None for h in self.a.flat):
            # enumeration members, by name, row by row
            lines = [f'  {size_str(self.a.shape)} {class_of(self.a.flat[0])} enumeration array', '']
            for row in self.a.reshape(self.a.shape[0], -1):
                lines.append('    ' + '    '.join(h.enum for h in row))
            return lines
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


def _all_props_link(obj):
    from .display import all_props_link
    return all_props_link(obj)


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
            'fontName': p.get('FontName', 'Helvetica'), 'margin': float(p.get('Margin', 3.0)), 'lineWidth': float(p.get('LineWidth', 0.5)),
            'lineStyle': p.get('LineStyle', '-')}


def _num(v):
    try:
        return float(np.asarray(v, float).reshape(-1)[0])
    except Exception:
        return None


# ---- properties worked out from others: sizes from the fonts, normals from the data ------------------------------------------

_PX_PER_PT = 4 / 3      # a point in pixels, as figures measure them


def _plot_box_px(ax):
    """The axes' Position in pixels of its figure (normalized units unless set otherwise)."""
    f = ax.figure()
    fw, fh = (np.asarray(f.props['Position'], float).reshape(-1)[2:4] if f is not None else (560.0, 420.0))
    pos = np.asarray(ax.props['Position'], float).reshape(-1)
    if ax.props.get('Units', 'normalized') == 'normalized':
        return pos[0] * fw, pos[1] * fh, pos[2] * fw, pos[3] * fh, fw, fh
    return pos[0], pos[1], pos[2], pos[3], fw, fh


def _text_size_px(lines, size_pt):
    """A text's width and height in pixels, estimated: the page measures what it draws, the engine counts letters."""
    em = size_pt * _PX_PER_PT
    return max((len(l) for l in lines), default=0) * 0.55 * em, max(len(lines), 1) * 1.2 * em


def axes_tight_inset(ax):
    """The room the tick labels, axis labels and title take outside the plot box, [left bottom right top] in the axes'
    Units: estimated from the fonts and the labels' lengths."""
    fs = float(ax.props.get('FontSize', 10.0))
    lab = fs * float(ax.props.get('LabelFontSizeMultiplier', 1.1))

    def labels(k):
        try:
            v = ax.get_value(k + 'TickLabel')
            return [py_str(x) for x in v.a.reshape(-1)] if isinstance(v, Cell) else []
        except Exception:
            return []
    yl = labels('Y')
    left = _text_size_px([max(yl, key=len)] if yl else [], fs)[0] + 6
    if py_str(ax.ylabel.get_value('String')):
        left += 1.4 * lab * _PX_PER_PT
    bottom = 1.2 * fs * _PX_PER_PT + 4
    if py_str(ax.xlabel.get_value('String')):
        bottom += 1.4 * lab * _PX_PER_PT
    top = 0.0
    if py_str(ax.title.get_value('String')):
        top += 1.4 * fs * float(ax.props.get('TitleFontSizeMultiplier', 1.1)) * _PX_PER_PT
    if py_str(ax.subtitle.get_value('String')):
        top += 1.3 * fs * _PX_PER_PT
    xl = labels('X')
    right = _text_size_px([xl[-1]] if xl else [], fs)[0] / 2
    _, _, _, _, fw, fh = _plot_box_px(ax)
    if ax.props.get('Units', 'normalized') == 'normalized':
        return np.array([[left / fw, bottom / fh, right / fw, top / fh]])
    return np.array([[left, bottom, right, top]])


def text_extent(t):
    """A text's box [left bottom width height] in its Units: its size estimated from the font and the letters, placed by
    its alignment; in data units through its axes' limits and size."""
    v = t.get_value('String')
    lines = [py_str(x) for x in v.a.reshape(-1)] if isinstance(v, Cell) else (v.row_strs() if isinstance(v, Char) and v.a.shape[0] > 1 else [py_str(v)])
    w, h = _text_size_px(lines, float(t.props.get('FontSize', 10.0)))
    pos = np.asarray(t.props['Position'], float).reshape(-1)
    ha, va = t.props.get('HorizontalAlignment', 'left'), t.props.get('VerticalAlignment', 'middle')
    dx = {'left': 0.0, 'center': -0.5, 'right': -1.0}.get(ha, 0.0)
    dy = {'bottom': 0.0, 'baseline': -0.2, 'middle': -0.5, 'cap': -0.85, 'top': -1.0}.get(va, -0.5)
    units = t.props.get('Units', 'data')
    ax = t.parent if isinstance(t.parent, Axes) else None
    if units == 'pixels' or ax is None:
        sx = sy = 1.0
    else:
        _, _, bw, bh, _, _ = _plot_box_px(ax)
        if units == 'normalized':
            sx, sy = 1 / max(bw, 1e-9), 1 / max(bh, 1e-9)
        else:
            xl = np.asarray(ax.get_value('XLim'), float).reshape(-1)
            yl = np.asarray(ax.get_value('YLim'), float).reshape(-1)
            sx, sy = (xl[1] - xl[0]) / max(bw, 1e-9), (yl[1] - yl[0]) / max(bh, 1e-9)
    return np.array([[pos[0] + dx * w * sx, pos[1] + dy * h * sy, w * sx, h * sy]])


def _alpha_values(c):
    """An object's alpha data as given (AlphaData, or a patch's FaceVertexAlphaData), or None."""
    k = 'FaceVertexAlphaData' if c.TYPE == 'patch' else 'AlphaData'
    v = c.props.get(k)
    if v is None or not numel(v) or isinstance(v, (Char, Str)):
        return None
    return np.asarray(v, float)


def auto_alim(ax):
    """The alpha limits from the data mapped through the alphamap ('scaled'), as CLim's from the colours."""
    lo, hi = math.inf, -math.inf
    for c in drawn_children(ax):
        if not c.valid or c.props.get('AlphaDataMapping') != 'scaled' or c.TYPE not in ('surface', 'patch', 'image'):
            continue
        a = _alpha_values(c)
        # a single value (a surface's AlphaData of 1 by default) leaves the limits as they are
        if a is None or a.size < 2:
            continue
        a = a[np.isfinite(a)]
        if ax.props.get('AlphaScale') == 'log':
            a = a[a > 0]
        if a.size:
            lo, hi = min(lo, float(a.min())), max(hi, float(a.max()))
    if lo == math.inf:
        return [0.0, 1.0]
    return [lo, hi] if hi > lo else [lo - 1, hi + 1]


def mapped_alpha(c, ax, a):
    """Alpha data as opacities from 0 to 1: as they are ('none'), as indices into the axes' Alphamap ('direct', from 1), or
    through ALim onto the Alphamap ('scaled'; on a log scale with AlphaScale 'log')."""
    a = np.asarray(a, float)
    mapping = c.props.get('AlphaDataMapping', 'none')
    if mapping == 'none':
        return np.clip(np.nan_to_num(a, nan=0.0), 0, 1)
    amap = np.asarray(ax.props.get('Alphamap'), float).reshape(-1) if ax is not None else np.linspace(0, 1, 64)
    if not amap.size:
        amap = np.linspace(0, 1, 64)
    n = amap.size
    if mapping == 'direct':
        idx = np.clip(np.nan_to_num(np.floor(a), nan=1) - 1, 0, n - 1).astype(int)
        return amap[idx]
    lo, hi = (np.asarray(ax.get_value('ALim'), float).reshape(-1) if ax is not None else (0.0, 1.0))
    if ax is not None and ax.props.get('AlphaScale') == 'log' and lo > 0 and hi > lo:
        with np.errstate(all='ignore'):
            t = (np.log10(np.where(a > 0, a, lo)) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
    else:
        t = (a - lo) / (hi - lo) if hi > lo else np.full(a.shape, 0.5)
    idx = np.clip(np.floor(np.nan_to_num(t, nan=0.0) * n), 0, n - 1).astype(int)
    return amap[idx]


def surface_normals(s, faces=False):
    """A surface's normals: at each vertex the cross product of the tangents along its columns and its rows (upward for
    z = f(x, y) on an increasing grid), or for each face that of its diagonals; not made unit length."""
    Z = np.asarray(s.props['ZData'], float)
    if Z.ndim != 2 or Z.size == 0:
        return EMPTY()
    m, n = Z.shape
    X = np.asarray(s.props['XData'], float)
    Y = np.asarray(s.props['YData'], float)
    X = np.broadcast_to(X.reshape(1, -1), (m, n)) if X.size == n and X.shape != (m, n) else (X if X.shape == (m, n) else np.broadcast_to(np.arange(1.0, n + 1), (m, n)))
    Y = np.broadcast_to(Y.reshape(-1, 1), (m, n)) if Y.size == m and Y.shape != (m, n) else (Y if Y.shape == (m, n) else np.broadcast_to(np.arange(1.0, m + 1).reshape(-1, 1), (m, n)))
    P = np.stack([X, Y, Z], axis=2)
    if faces:
        if m < 2 or n < 2:
            return EMPTY()
        a = P[1:, 1:] - P[:-1, :-1]
        b = P[:-1, 1:] - P[1:, :-1]
        return np.cross(b, a)
    tj = np.gradient(P, axis=1) if n > 1 else np.zeros_like(P)
    ti = np.gradient(P, axis=0) if m > 1 else np.zeros_like(P)
    return np.cross(tj, ti)


def _patch_faces(p):
    """A patch's faces (rows of vertex indices from 0, -1 for none) and vertices, from Faces and Vertices or from its
    XData, YData and ZData (a column each face)."""
    F, V = p.props.get('Faces'), p.props.get('Vertices')
    if numel(F) and numel(V):
        F = np.asarray(F, float)
        F = np.where(np.isfinite(F), F - 1, -1).astype(int)
        return F.reshape(F.shape[0], -1), np.asarray(V, float).reshape(np.asarray(V).shape[0], -1)
    X = np.asarray(p.props.get('XData'), float)
    if X.size == 0:
        return np.zeros((0, 0), int), np.zeros((0, 3))
    X = X.reshape(-1, 1) if X.ndim < 2 or X.shape[0] == 1 else X
    Y = np.asarray(p.props.get('YData'), float).reshape(X.shape)
    Z = np.asarray(p.props.get('ZData'), float)
    Z = Z.reshape(X.shape) if Z.size == X.size else np.zeros(X.shape)
    V = np.column_stack([X.reshape(-1, order='F'), Y.reshape(-1, order='F'), Z.reshape(-1, order='F')])
    F = np.arange(X.size).reshape(X.shape[1], X.shape[0])
    return F, V


def patch_normals(p, faces=False):
    """A patch's normals: each face's by Newell's method (its area times its unit normal), and at each vertex the sum
    over the faces that meet there."""
    F, V = _patch_faces(p)
    if not F.size:
        return EMPTY()
    V3 = V if V.shape[1] == 3 else np.column_stack([V[:, :2], np.zeros(len(V))])
    N = np.zeros((F.shape[0], 3))
    for i, row in enumerate(F):
        idx = row[row >= 0]
        if idx.size < 3:
            continue
        a, b = V3[idx], V3[np.roll(idx, -1)]
        N[i] = 0.5 * np.array([np.sum((a[:, 1] - b[:, 1]) * (a[:, 2] + b[:, 2])), np.sum((a[:, 2] - b[:, 2]) * (a[:, 0] + b[:, 0])),
                               np.sum((a[:, 0] - b[:, 0]) * (a[:, 1] + b[:, 1]))])
    if faces:
        return N
    out = np.zeros((V3.shape[0], 3))
    for i, row in enumerate(F):
        for j in row[row >= 0]:
            out[j] += N[i]
    return out


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
        if p.get('LineJoin', 'round') != 'round':
            d['lineJoin'] = p['LineJoin']
    elif t == 'surface':
        d.update(x=_arr(p['XData']), y=_arr(p['YData']), z=_arr(p['ZData']), c=_arr(p['CData']) if numel(p['CData']) else None,
                 faceColor=_color(p['FaceColor']), edgeColor=_color(p['EdgeColor']),
                 faceAlpha=p['FaceAlpha'] if isinstance(p['FaceAlpha'], str) else float(_num(p['FaceAlpha'])),
                 edgeAlpha=float(_num(p['EdgeAlpha'])) if not isinstance(p['EdgeAlpha'], str) else 1.0,
                 lineStyle=p['LineStyle'], lineWidth=float(p['LineWidth']), meshStyle=p['MeshStyle'],
                 lighting=p['FaceLighting'], marker=p['Marker'], markerSize=float(p['MarkerSize']),
                 cmapping=p['CDataMapping'])
        # FaceAlpha 'flat' or 'interp': the faces' opacities from AlphaData, through the alphamap as its mapping says
        if isinstance(p['FaceAlpha'], str) and p['FaceAlpha'] in ('flat', 'interp'):
            ad = _alpha_values(c)
            if ad is not None:
                m_ = mapped_alpha(c, ax, ad)
                if ad.size > 1:
                    d['alphaData'] = _arr(m_.reshape(ad.shape))
                elif float(m_.reshape(-1)[0]) != 1.0:
                    d['faceAlpha'] = float(m_.reshape(-1)[0])
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
                 mfc=_color(p['MarkerFaceColor']), rings=bool(getattr(c, 'rings', False)))
        # FaceAlpha 'flat' or 'interp': each face's opacity from FaceVertexAlphaData (one for each face, or each vertex)
        if isinstance(p['FaceAlpha'], str) and p['FaceAlpha'] in ('flat', 'interp'):
            ad = _alpha_values(c)
            if ad is not None:
                d['fva'] = _arr(mapped_alpha(c, ax, ad).reshape(-1, 1))
                d['faceAlphaMode'] = p['FaceAlpha']
    elif t == 'image':
        cd = p['CData']
        a = np.asarray(cd.a if type(cd) is Char else cd)
        if a.dtype == np.uint8:
            a = a.astype(float) / 255.0 if a.ndim == 3 else a.astype(float)
        d.update(c=_arr(a), x=_arr(p['XData']), y=_arr(p['YData']), cmapping=p['CDataMapping'],
                 alpha=float(_num(p['AlphaData'])) if numel(p['AlphaData']) == 1 else 1.0,
                 rgb=bool(a.ndim == 3))
        # alpha data: a value for each pixel, or one mapped through the alphamap, as opacities
        ad = _alpha_values(c)
        if ad is not None and (ad.size > 1 or p.get('AlphaDataMapping', 'none') != 'none'):
            m_ = mapped_alpha(c, ax, ad)
            if ad.size > 1:
                d['alphaData'] = _arr(m_.reshape(ad.shape))
            else:
                d['alpha'] = float(m_.reshape(-1)[0])
        if p.get('Interpolation', 'nearest') == 'bilinear':
            d['interpolation'] = 'bilinear'
    elif t == 'text':
        d.update(_text_json(c))
    elif t == 'light':
        d.update(position=[float(x) for x in np.asarray(p['Position'], float).reshape(-1)], style=p['Style'], color=_color(p['Color']))
    else:
        # a series
        d['type'] = 'series'
        d['kind'] = c.kind
        for k in ('XData', 'YData', 'ZData', 'CData', 'UData', 'VData', 'WData', 'SizeData', 'YNegativeDelta', 'YPositiveDelta', 'XNegativeDelta', 'XPositiveDelta'):
            v = p.get(k)
            if v is not None and type(v) is not Char and not isinstance(v, str) and numel(v):
                d[k[0].lower() + k[1:]] = _arr(v)
        d.update(faceColor=_color(p['FaceColor']), edgeColor=_color(p['EdgeColor']), color=_color(p['Color']),
                 lineStyle=p['LineStyle'], lineWidth=float(p['LineWidth']), marker=p['Marker'], markerSize=float(p['MarkerSize']),
                 mfc=_color(p['MarkerFaceColor']), mec=_color(p['MarkerEdgeColor']), faceAlpha=float(_num(p['FaceAlpha']) or 1.0),
                 barWidth=float(p['BarWidth']), baseValue=float(p['BaseValue']), showText=bool(p['ShowText']),
                 fill=bool(p['Fill']), horizontal=bool(p['Horizontal']), capSize=float(p['CapSize']),
                 maxHeadSize=float(p['MaxHeadSize']), labels=p.get('Labels') or [])
        for k in ('MarkerFaceAlpha', 'MarkerEdgeAlpha'):
            v = p[k]
            d[k[0].lower() + k[1:]] = 1.0 if isinstance(v, str) else float(_num(v))
        if c.kind == 'bubblechart':
            d['bubbleSize'] = _arr(bubble_diameters(ax, c).reshape(1, -1))
        for k, v in c.extra.items():
            if isinstance(v, np.ndarray):
                d[k] = _arr(v)
            elif isinstance(v, (list, str, float, int, bool)) or v is None:
                d[k] = v
    ext = getattr(c, 'serial_extra', None)
    if ext is not None:
        d.update(ext())
    return d


def bubble_lim(ax):
    """The sizes that the smallest and the largest bubbles stand for: BubbleLim,
    or in auto mode the range of the sizes of the axes' bubble charts."""
    if ax.props['BubbleLimMode'] == 'manual':
        return [float(v) for v in np.asarray(ax.props['BubbleLim'], float).reshape(-1)]
    lo, hi = math.inf, -math.inf
    for c in ax.children:
        if c.valid and isinstance(c, Series) and c.kind == 'bubblechart':
            a = np.asarray(c.props['SizeData'], float).reshape(-1)
            a = a[np.isfinite(a)]
            if a.size:
                lo, hi = min(lo, float(a.min())), max(hi, float(a.max()))
    return [0.0, 1.0] if lo > hi else [lo, hi]


def bubble_diameters(ax, c):
    """Each bubble's diameter in points. A size is clipped to BubbleLim, and
    its place between the two ends is its bubble's place between the areas of
    the smallest and the largest bubble of BubbleSizeRange. When all the
    sizes are the same, the bubbles are the size halfway."""
    lo, hi = bubble_lim(ax)
    dmin, dmax = (float(v) for v in np.asarray(ax.props['BubbleSizeRange'], float).reshape(-1))
    s = np.asarray(c.props['SizeData'], float).reshape(-1)
    with np.errstate(invalid='ignore'):
        f = np.clip((s - lo) / (hi - lo), 0.0, 1.0) if hi > lo else np.where(np.isfinite(s), 0.5, np.nan)
    return np.sqrt(dmin ** 2 + f * (dmax ** 2 - dmin ** 2))


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
        'id': ax.id, 'type': 'axes', 'kind': ax.kind, 'geo': ax.kind == 'geo',
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
        'camTarget': [float(x) for x in p['CameraTarget'].reshape(-1)] if p['CameraTargetMode'] == 'manual' else None,
        'camUp': [float(x) for x in p['CameraUpVector'].reshape(-1)] if p['CameraUpVectorMode'] == 'manual' else None,
        'xkind': (getattr(ax, 'kinds', None) or {}).get('x'), 'ykind': (getattr(ax, 'kinds', None) or {}).get('y'),
        'zkind': (getattr(ax, 'kinds', None) or {}).get('z'),
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
        'camZoom': ax.camera_zoom(),
        'visible': bool(p['Visible']), 'layer': p['Layer'],
        'fontName': p['FontName'], 'fontWeight': p['FontWeight'], 'tickLabelInterpreter': p['TickLabelInterpreter'],
        'tickLength': [float(x) for x in np.asarray(p['TickLength'], float).reshape(-1)],
        'xminortick': bool(p['XMinorTick']), 'yminortick': bool(p['YMinorTick']), 'zminortick': bool(p['ZMinorTick']),
        'minorGridAlpha': float(p['MinorGridAlpha']), 'minorGridLineStyle': p['MinorGridLineStyle'],
        'titleSize': float(p['TitleFontSizeMultiplier']), 'labelSize': float(p['LabelFontSizeMultiplier']),
        'title': _text_json(ax.title), 'subtitle': _text_json(ax.subtitle), 'xlabel': _text_json(ax.xlabel), 'ylabel': _text_json(ax.ylabel),
        'zlabel': _text_json(ax.zlabel), 'cmap': _b64(np.asarray(cmap, float)),
        'children': [serialize_child(c, ax) for c in reversed(drawn_children(ax)) if c.valid and not getattr(c, 'hidden', False)],
        'xtickformat': (getattr(ax, 'tickfmt', None) or {}).get('X'), 'ytickformat': (getattr(ax, 'tickfmt', None) or {}).get('Y'),
        'ztickformat': (getattr(ax, 'tickfmt', None) or {}).get('Z'), 'ztickrot': float(p['ZTickLabelRotation']),
        'polar': None if ax.kind != 'polar' else {
            'rlim': [float(x) for x in p['RLim'].reshape(-1)] if p['RLimMode'] == 'manual' else None,
            'rtick': [float(x) for x in np.asarray(p['RTick'], float).reshape(-1)] if p['RTickMode'] == 'manual' else None,
            'rticklabel': p['RTickLabel'] if p['RTickLabelMode'] == 'manual' else None,
            'thetatick': [float(x) for x in np.asarray(p['ThetaTick'], float).reshape(-1)],
            'thetaticklabel': p['ThetaTickLabel'] if p['ThetaTickLabelMode'] == 'manual' else None,
            'thetadir': p['ThetaDir'], 'thetazero': p['ThetaZeroLocation']},
        'texts': [],
        'yy': None,
        'units': p['Units'], 'fontUnits': p['FontUnits'],
        'parent': ax.parent.id if ax.parent is not None and ax.parent.TYPE not in ('figure', 'axes') else None,
    }
    d.update(_interact_json(ax))
    # the title's alignment and the minor grid's colour, when not their defaults (the pages stored before stay as they were)
    if p.get('TitleHorizontalAlignment', 'center') != 'center':
        d['titleAlign'] = p['TitleHorizontalAlignment']
    if p.get('FontAngle', 'normal') == 'italic':
        d['fontAngle'] = 'italic'
    if p.get('BoxStyle', 'back') == 'full':
        d['boxStyle'] = 'full'
    if p.get('ColorScale', 'linear') == 'log':
        d['colorScale'] = 'log'
    if p.get('ClippingStyle', '3dbox') == 'rectangle':
        d['clippingStyle'] = 'rectangle'
    if _color(p.get('MinorGridColor', (0.1, 0.1, 0.1))) != _color((0.1, 0.1, 0.1)):
        d['minorGridColor'] = _color(p['MinorGridColor'])
    if ax.kind == 'geo':
        # the basemap's name, and for one of addCustomBasemap its tiles (pylab-basemap.js)
        eg = getattr(ax, 'extra_geo', {})
        d['basemap'] = eg.get('basemap', 'none')
        d['basemapCustom'] = eg.get('custom')
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
                for k in ('Color', 'LineStyle', 'LineWidth', 'Marker', 'MarkerSize', 'MarkerFaceColor', 'MarkerEdgeColor', 'FaceColor', 'EdgeColor', 'FaceAlpha', 'MarkerFaceAlpha'):
                    if k in ep:
                        v = ep[k]
                        ed[k[0].lower() + k[1:]] = _color(v) if 'Color' in k else (float(_num(v)) if k in ('LineWidth', 'MarkerSize', 'FaceAlpha', 'MarkerFaceAlpha') and not isinstance(v, str) else v)
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
                                   'direction': cp['Direction'], 'box': bool(cp['Box']), 'tickDirection': cp['TickDirection']})
        elif isinstance(c, Shape):
            d['annotations'].append(c.serialize())
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
                        'PaperType': 'usletter', 'PaperOrientation': 'portrait', 'PaperPosition': lambda: np.array([[0.25, 2.5, 8.0, 6.0]]),
                        'Selected': False, 'SelectionHighlight': True,
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
Polygon.DEFAULTS = {**Patch.DEFAULTS, **Polygon.OWN_DEFAULTS}
Polygon.ALIASES = Patch.ALIASES
Rectangle.DEFAULTS = {**Patch.DEFAULTS, **Rectangle.OWN_DEFAULTS}
Rectangle.ALIASES = Patch.ALIASES
for _C in (Group, Transform):
    _C.DEFAULTS = {**_C.DEFAULTS, **INTERACT}
# where a plot's data come from, for refreshdata
for _C in (Line, Surface, Series):
    _C.DEFAULTS.update({'XDataSource': '', 'YDataSource': '', 'ZDataSource': ''})


def register(*classes):
    """Property names as typed, matched without regard to case; the other
    names some properties go by."""
    for C in classes:
        names = list(C.DEFAULTS) + list(_EXTRA.get(C, ()))
        C._lower = {n.lower(): n for n in names}
        C._alias = {a.lower(): n for a, n in getattr(C, 'ALIASES', {}).items() if n in C.DEFAULTS}


_EXTRA = {Axes: ('Title', 'Subtitle', 'XLabel', 'YLabel', 'ZLabel', 'Legend'), Colorbar: ('Label',), Root: ('CallbackObject',)}
register(Root, Figure, Axes, Line, Surface, Patch, Polygon, Rectangle, Group, Transform, Image, Text, Legend, Colorbar, Light, Series,
         *SHAPES.values())
GObj._lower = {}
GObj._alias = {}
