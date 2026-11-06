"""User-interface objects: controls, panels, button groups, tables, tab
groups and tabs, menus, context menus, toolbars and their tools. They are
handles with properties like the other graphics objects (graphics_base);
the page builds them as HTML over the figure's canvas from what
serialize_ui() makes, and tells uievents what people do with them.
"""
import numpy as np

from .values import Char, Cell, Str, EMPTY, py_str, numel, F64
from .graphics_base import (GObj, HArr, ROOT, INTERACT, register, gerr, choice, _arr, _color, has_callback, _interact_json,
                            serialize_axes)

UNITS = ('pixels', 'normalized', 'characters', 'points', 'inches', 'centimeters')
# a unit in pixels, across and up ('characters': a letter of the default font)
UNIT_PX = {'pixels': (1.0, 1.0), 'points': (4 / 3, 4 / 3), 'inches': (96.0, 96.0), 'centimeters': (96 / 2.54, 96 / 2.54),
           'characters': (5.0, 13.0)}
STYLES = ('pushbutton', 'togglebutton', 'checkbox', 'radiobutton', 'edit', 'text', 'slider', 'listbox', 'popupmenu', 'frame')
CONTROLS = ('uicontrol', 'uipanel', 'uibuttongroup', 'uitable', 'uitabgroup', 'uicomp', 'uigridlayout')
CONTAINERS = ('figure', 'uipanel', 'uibuttongroup', 'uitabgroup', 'uitab')
TAB_STRIP = 26.0           # the height of a tab group's tabs, in pixels


# ---- where things are -----------------------------------------------------------------------

def _pos(o):
    return np.asarray(o.props['Position'], float).reshape(-1)


def inner_px(c):
    """The size in pixels of the area a container gives its children."""
    if c is None:
        return 560.0, 420.0
    t = c.TYPE
    if t == 'figure':
        pos = _pos(c)
        if c.props['Units'] == 'normalized':
            scr = np.asarray(ROOT.props['ScreenSize'], float).reshape(-1)
            return pos[2] * scr[2], pos[3] * scr[3]
        sx, sy = UNIT_PX.get(c.props['Units'], (1.0, 1.0))
        return pos[2] * sx, pos[3] * sy
    if t == 'uitab':
        w, h = inner_px(c.parent)
        return w, max(0.0, h - TAB_STRIP)
    if t == 'uigridlayout':
        g = getattr(c, 'px', None)
        return (g[2], g[3]) if g else inner_px(c.parent)
    _, _, w, h = to_pixels(c)
    if t in ('uipanel', 'uibuttongroup'):
        b = 2 * float(c.props['BorderWidth']) if c.props['BorderType'] != 'none' else 0.0
        title = float(c.props['FontSize']) * 4 / 3 + 4 if c.props['Title'] else 0.0
        return max(0.0, w - b), max(0.0, h - b - title)
    return w, h


def to_pixels(o, pos=None, units=None):
    """[x y w h] of an object in pixels of its container."""
    p = _pos(o) if pos is None else np.asarray(pos, float).reshape(-1)
    u = units or o.props['Units']
    if u == 'normalized':
        W, H = inner_px(o.parent)
        return p * np.array([W, H, W, H])
    sx, sy = UNIT_PX.get(u, (1.0, 1.0))
    return p * np.array([sx, sy, sx, sy])


def from_pixels(o, px, units):
    """Pixels of an object's container as a Position in units."""
    if units == 'normalized':
        W, H = inner_px(o.parent)
        return np.asarray(px, float) / np.array([W or 1.0, H or 1.0, W or 1.0, H or 1.0])
    sx, sy = UNIT_PX.get(units, (1.0, 1.0))
    return np.asarray(px, float) / np.array([sx, sy, sx, sy])


def set_placed(o, k, value):
    """Position, Units (converting Units keeps the object where it is) and
    CurrentPoint, for axes and controls alike."""
    if k == 'Position':
        a = np.asarray(value.a if type(value) is Char else value, float).reshape(-1)
        if a.size != 4:
            raise gerr('Value must be a 4-element vector.', 'MATLAB:hg:shaped_arrays:FourElementVector')
        o.props[k] = a.reshape(1, 4)
        return
    if k == 'CurrentPoint':
        o.props[k] = np.asarray(value, float)
        return
    u = choice(value, UNITS)
    if u not in UNITS:
        raise gerr(f"'{py_str(value)}' is not a valid value for Units. Use one of these values: {_choices(UNITS)}.")
    if u != o.props['Units']:
        px = to_pixels(o)
        o.props['Units'] = u
        o.props['Position'] = from_pixels(o, px, u).reshape(1, 4)


def _choices(names):
    return ' | '.join(f"'{n}'" for n in names)


def jnum(v):
    """A number for the page's JSON, which has no NaN or Inf: those go as text."""
    v = float(v)
    if v != v:
        return 'NaN'
    if v in (float('inf'), float('-inf')):
        return 'Inf' if v > 0 else '-Inf'
    return v


def lines_of(v):
    """A String as its lines: a char matrix by rows, a cell or string array by
    elements; a number as its text."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [str(x) for x in v]
    t = type(v)
    if t is Char:
        if v.a.shape[0] <= 1:
            return [v.str()]
        return [r.rstrip(' \0') for r in v.row_strs()]
    if t is Str:
        return [s or '' for s in v.a.reshape(-1, order='F')]
    if t is Cell:
        out = []
        for x in v.a.reshape(-1, order='F'):
            out.append(py_str(x) if type(x) in (Char, Str) else (_num_text(x)))
        return out
    return [_num_text(v)]


def _num_text(x):
    try:
        a = np.asarray(x, float).reshape(-1)
    except Exception:
        return ''
    return ' '.join(f'{v:g}' for v in a)


def _font_px(o):
    s = float(o.props.get('FontSize', 8.0))
    u = o.props.get('FontUnits', 'points')
    if u == 'pixels':
        return s
    if u == 'normalized':
        _, _, _, h = to_pixels(o)
        return s * h
    return s * UNIT_PX.get(u, (4 / 3, 4 / 3))[1]


TEXT_UNITS = ('data', 'normalized', 'pixels', 'points', 'inches', 'centimeters', 'characters')


def set_text_units(t, value):
    """A text's Units, its Position converted so the text stays where it is:
    data through the axes' limits, the rest from the axes' lower left."""
    u = choice(value, TEXT_UNITS)
    if u not in TEXT_UNITS:
        raise gerr(f"'{py_str(value)}' is not a valid value for Units. Use one of these values: {_choices(TEXT_UNITS)}.")
    old = t.props.get('Units', 'data')
    ax = t.parent
    if u != old and ax is not None and ax.TYPE == 'axes':
        p = np.asarray(t.props['Position'], float).reshape(-1).copy()
        _, _, w, h = to_pixels(ax)
        if 'data' in (u, old):
            from .glayout import auto_limits
            auto = None
            span = []
            for k in ('XLim', 'YLim'):
                if ax.props.get(k + 'Mode') == 'manual':
                    lo, hi = (float(v) for v in np.asarray(ax.props[k], float).reshape(-1)[:2])
                else:
                    auto = auto or auto_limits(ax)
                    lo, hi = (float(v) for v in np.asarray(auto[k], float).reshape(-1)[:2])
                span.append((lo, (hi - lo) or 1.0))

        def per(unit, i):
            """Pixels per unit along x (i 0) or y (i 1), and where 0 is."""
            if unit == 'data':
                return (w, h)[i] / span[i][1], span[i][0]
            if unit == 'normalized':
                return (w, h)[i], 0.0
            return UNIT_PX[unit][i], 0.0
        for i in (0, 1):
            k0, o0 = per(old, i)
            k1, o1 = per(u, i)
            p[i] = (p[i] - o0) * k0 / k1 + o1
        t.props['Position'] = p.reshape(1, -1)
    t.props['Units'] = u


FONT_UNITS = ('points', 'pixels', 'inches', 'centimeters', 'normalized')


def _font_ref_px(o):
    """The height a normalized FontSize is a part of: a text's axes, an axes'
    or a control's own."""
    if o.TYPE == 'text':
        o = o.parent
    try:
        if o is None or o.TYPE in ('figure', 'uitab'):
            return inner_px(o)[1]
        return float(to_pixels(o)[3]) or 1.0
    except Exception:
        return 420.0


def set_font_units(o, value):
    """FontUnits, with FontSize changed to keep the letters their size, as
    FontSize given before FontUnits ('FontSize', 20, 'FontUnits',
    'normalized') means a size in the units it had."""
    u = choice(value, FONT_UNITS)
    if u not in FONT_UNITS:
        raise gerr(f"'{py_str(value)}' is not a valid value for FontUnits. Use one of these values: {_choices(FONT_UNITS)}.")
    old = o.props.get('FontUnits', 'points')
    if u != old and 'FontSize' in o.props:
        ref = _font_ref_px(o) if 'normalized' in (u, old) else 1.0
        per = lambda unit: ref if unit == 'normalized' else UNIT_PX[unit][1]
        o.props['FontSize'] = float(o.props['FontSize']) * per(old) / per(u)
    o.props['FontUnits'] = u


class _Placed(GObj):
    """An object with a Position in the Units of its container."""

    def set_value(self, k, value):
        if k in ('Position', 'Units'):
            set_placed(self, k, value)
            self.touch()
            return
        super().set_value(k, value)


# ---- controls ------------------------------------------------------------------------------------

class UIControl(_Placed):
    TYPE = 'uicontrol'
    CLASSNAME = 'matlab.ui.control.UIControl'
    DEFAULTS = {'Style': 'pushbutton', 'String': lambda: Char.of(''), 'Value': 0.0, 'Min': 0.0, 'Max': 1.0, 'Callback': '',
                'Position': lambda: np.array([[20.0, 20.0, 60.0, 20.0]]), 'Units': 'pixels',
                'BackgroundColor': (0.94, 0.94, 0.94), 'ForegroundColor': (0.0, 0.0, 0.0), 'FontSize': 8.0,
                'FontName': 'Helvetica', 'FontWeight': 'normal', 'FontAngle': 'normal', 'FontUnits': 'points',
                'HorizontalAlignment': 'center', 'Enable': True, 'Visible': True, 'Tag': '', 'UserData': lambda: EMPTY(),
                'TooltipString': '', 'SliderStep': lambda: np.array([[0.01, 0.1]]), 'ListboxTop': 1.0,
                'CData': lambda: EMPTY(), 'KeyPressFcn': '', 'KeyReleaseFcn': '', 'Extent': None, **INTERACT}
    ALIASES = {'Tooltip': 'TooltipString', 'ContextMenu': 'UIContextMenu'}
    SHOWN = ['Style', 'String', 'BackgroundColor', 'Callback', 'Value', 'Position', 'Units']

    def get_value(self, k):
        if k == 'String':
            return self.props['String']
        if k == 'Value':
            return self.props['Value']
        if k == 'Extent':
            lines = self.lines() or ['']
            fs = _font_px(self)
            px = [0.0, 0.0, max(len(s) for s in lines) * fs * 0.56 + 4, len(lines) * fs * 1.25 + 4]
            return from_pixels(self, px, self.props['Units']).reshape(1, 4)
        return super().get_value(k)

    def set_value(self, k, value):
        if k == 'Style':
            s = choice(value, STYLES)       # an abbreviation that names one: 'push', 'radio', 'popup'
            if s not in STYLES:
                raise gerr(f"'{py_str(value)}' is not a valid value for Style. Use one of these values: {_choices(STYLES)}.")
            self.props[k] = s
            return
        if k == 'String':
            if type(value) in (Char, Cell, Str):
                self.props[k] = value
            elif isinstance(value, (float, int, np.ndarray)) and not isinstance(value, bool):
                self.props[k] = Char.of(_num_text(value)) if numel(value) else Char.of('')
            else:
                self.props[k] = Char.of(py_str(value))
            return
        if k == 'Value':
            self.props[k] = _value(value)
            return
        if k in ('Min', 'Max', 'ListboxTop', 'FontSize'):
            self.props[k] = float(np.asarray(value, float).reshape(-1)[0])
            return
        if k == 'SliderStep':
            a = np.asarray(value, float).reshape(-1)
            if a.size != 2:
                raise gerr('SliderStep must be a 2-element vector.')
            self.props[k] = a.reshape(1, 2)
            return
        if k == 'CData':
            self.props[k] = np.asarray(value.a if type(value) is Char else value)
            return
        if k == 'HorizontalAlignment':
            self.props[k] = py_str(value).lower()
            return
        super().set_value(k, value)

    def lines(self):
        ls = lines_of(self.props['String'])
        if self.props['Style'] in ('listbox', 'popupmenu') and len(ls) == 1 and '|' in ls[0]:
            ls = ls[0].split('|')
        return ls

    def selected(self):
        """Value as a list of numbers."""
        v = self.props['Value']
        return [float(x) for x in np.asarray(v, float).reshape(-1)] if numel(v) else []


def _value(v):
    if type(v) is Char:
        v = v.a.astype(float)
    a = np.asarray(v, float)
    if a.size == 0:
        return EMPTY()
    if a.size == 1:
        return float(a.reshape(-1)[0])
    return a.reshape(1, -1) if a.ndim <= 2 and min(a.shape) == 1 else a


class UIPanel(_Placed):
    TYPE = 'uipanel'
    CLASSNAME = 'matlab.ui.container.Panel'
    DEFAULTS = {'Title': '', 'TitlePosition': 'lefttop', 'BorderType': 'etchedin', 'BorderWidth': 1.0,
                'BackgroundColor': (0.94, 0.94, 0.94), 'ForegroundColor': (0.0, 0.0, 0.0), 'HighlightColor': (1.0, 1.0, 1.0),
                'ShadowColor': (0.7, 0.7, 0.7), 'Position': lambda: np.array([[0.0, 0.0, 1.0, 1.0]]), 'Units': 'normalized',
                'FontSize': 8.0, 'FontName': 'Helvetica', 'FontWeight': 'normal', 'FontAngle': 'normal', 'FontUnits': 'points',
                'Visible': True, 'Tag': '', 'UserData': lambda: EMPTY(), 'Clipping': True, 'ResizeFcn': '', 'SizeChangedFcn': '',
                **INTERACT}
    SHOWN = ['Title', 'BackgroundColor', 'Position', 'Units']

    def set_value(self, k, value):
        if k in ('BorderWidth', 'FontSize'):
            self.props[k] = float(np.asarray(value, float).reshape(-1)[0])
            return
        if k in ('BorderType', 'TitlePosition'):
            self.props[k] = py_str(value).lower()
            return
        super().set_value(k, value)


class UIButtonGroup(UIPanel):
    TYPE = 'uibuttongroup'
    CLASSNAME = 'matlab.ui.container.ButtonGroup'
    DEFAULTS = {**UIPanel.DEFAULTS, 'SelectedObject': None, 'SelectionChangedFcn': ''}
    ALIASES = {'SelectionChangeFcn': 'SelectionChangedFcn', 'ContextMenu': 'UIContextMenu'}

    def buttons(self):
        return [c for c in reversed(self.children) if c.valid and c.TYPE == 'uicontrol' and c.props['Style'] in ('radiobutton', 'togglebutton')]

    def get_value(self, k):
        if k == 'SelectedObject':
            s = self.selection()
            return s if s is not None else EMPTY()
        return super().get_value(k)

    def selection(self):
        for b in self.buttons():
            if b.selected() == [b.props['Max']]:
                return b
        return None

    def set_value(self, k, value):
        if k == 'SelectedObject':
            if isinstance(value, HArr) and value.a.size == 1:
                value = value.a.flat[0]
            if value not in self.buttons():
                raise gerr('SelectedObject must be a radio button or toggle button of this button group.')
            self.select(value)
            return
        super().set_value(k, value)

    def select(self, b):
        for x in self.buttons():
            x.props['Value'] = x.props['Max'] if x is b else x.props['Min']
        self.touch()


class UITable(_Placed):
    TYPE = 'uitable'
    CLASSNAME = 'matlab.ui.control.Table'
    DEFAULTS = {'Data': lambda: EMPTY(), 'ColumnName': 'numbered', 'RowName': 'numbered', 'ColumnWidth': 'auto',
                'ColumnEditable': lambda: EMPTY(), 'ColumnFormat': lambda: Cell(np.empty((1, 0), object)),
                'CellEditCallback': '', 'CellSelectionCallback': '', 'Position': lambda: np.array([[20.0, 20.0, 300.0, 300.0]]),
                'Units': 'pixels', 'FontSize': 8.0, 'FontName': 'Helvetica', 'FontWeight': 'normal', 'FontAngle': 'normal',
                'FontUnits': 'points', 'BackgroundColor': lambda: np.array([[1.0, 1.0, 1.0], [0.94, 0.94, 0.94]]),
                'ForegroundColor': (0.0, 0.0, 0.0), 'RowStriping': True, 'Enable': True, 'Visible': True, 'Tag': '',
                'UserData': lambda: EMPTY(), 'TooltipString': '', 'KeyPressFcn': '', **INTERACT}
    ALIASES = {'Tooltip': 'TooltipString', 'ContextMenu': 'UIContextMenu'}
    SHOWN = ['Data', 'ColumnName', 'RowName', 'Position', 'Units']

    def get_value(self, k):
        if k in ('Data', 'ColumnName', 'RowName', 'ColumnWidth', 'ColumnEditable', 'ColumnFormat', 'BackgroundColor'):
            v = self.props[k]
            return Char.of(v) if isinstance(v, str) else v
        return super().get_value(k)

    def set_value(self, k, value):
        if k == 'Data':
            if type(value) in (Cell,) or isinstance(value, np.ndarray) or type(value) in (float, bool):
                self.props[k] = value if not isinstance(value, (float, bool)) else np.array([[float(value)]])
                return
            raise gerr('Data must be a numeric, logical or cell array.')
        if k in ('ColumnName', 'RowName', 'ColumnWidth'):
            word = 'auto' if k == 'ColumnWidth' else 'numbered'
            ls = lines_of(value) if type(value) in (Char, Str) else None
            if ls is not None and len(ls) == 1 and ls[0].lower() == word:
                self.props[k] = word
            elif not numel(value):
                self.props[k] = Cell(np.empty((0, 0), object))
            elif k == 'ColumnWidth' and type(value) is not Cell:
                raise gerr("ColumnWidth must be 'auto' or a cell array of widths.")
            else:
                self.props[k] = value
            return
        if k == 'ColumnEditable':
            self.props[k] = np.asarray(value, bool).reshape(1, -1) if numel(value) else EMPTY()
            return
        if k == 'BackgroundColor':
            a = np.asarray(value, float)
            if a.size % 3:
                raise gerr('BackgroundColor must be an m-by-3 matrix of RGB values.')
            self.props[k] = a.reshape(-1, 3)
            return
        if k == 'FontSize':
            self.props[k] = float(np.asarray(value, float).reshape(-1)[0])
            return
        super().set_value(k, value)


class UITabGroup(_Placed):
    TYPE = 'uitabgroup'
    CLASSNAME = 'matlab.ui.container.TabGroup'
    DEFAULTS = {'Position': lambda: np.array([[0.0, 0.0, 1.0, 1.0]]), 'Units': 'normalized', 'SelectedTab': None,
                'SelectionChangedFcn': '', 'TabLocation': 'top', 'Visible': True, 'Tag': '', 'UserData': lambda: EMPTY(), **INTERACT}
    SHOWN = ['SelectedTab', 'TabLocation', 'Position', 'Units']

    def tabs(self):
        return [c for c in reversed(self.children) if c.valid and c.TYPE == 'uitab']

    def selection(self):
        s = self.props.get('SelectedTab')
        if s is not None and s.valid and s.parent is self:
            return s
        tabs = self.tabs()
        return tabs[0] if tabs else None

    def get_value(self, k):
        if k == 'SelectedTab':
            s = self.selection()
            return s if s is not None else EMPTY()
        return super().get_value(k)

    def set_value(self, k, value):
        if k == 'SelectedTab':
            if isinstance(value, HArr) and value.a.size == 1:
                value = value.a.flat[0]
            if value not in self.tabs():
                raise gerr('SelectedTab must be a tab of this tab group.')
            self.props[k] = value
            return
        if k == 'TabLocation':
            self.props[k] = py_str(value).lower()
            return
        super().set_value(k, value)


class UITab(GObj):
    TYPE = 'uitab'
    CLASSNAME = 'matlab.ui.container.Tab'
    DEFAULTS = {'Title': '', 'BackgroundColor': (0.94, 0.94, 0.94), 'ForegroundColor': (0.0, 0.0, 0.0), 'Units': 'pixels',
                'TooltipString': '', 'Tag': '', 'UserData': lambda: EMPTY(), 'SizeChangedFcn': '', **INTERACT}
    ALIASES = {'Tooltip': 'TooltipString', 'ContextMenu': 'UIContextMenu'}
    SHOWN = ['Title', 'BackgroundColor']

    def getprop(self, name):
        if name.lower() == 'position':
            w, h = inner_px(self)
            return np.array([[1.0, 1.0, w, h]])
        return super().getprop(name)


# ---- menus and toolbars --------------------------------------------------------------------------

_ACTIVE = {'Interruptible': True, 'BusyAction': 'queue', 'CreateFcn': '', 'DeleteFcn': '', 'HandleVisibility': 'on',
           'BeingDeleted': False, 'Tag': '', 'UserData': lambda: EMPTY()}


class UIMenu(GObj):
    TYPE = 'uimenu'
    CLASSNAME = 'matlab.ui.container.Menu'
    DEFAULTS = {'Label': '', 'Callback': '', 'Accelerator': '', 'Separator': False, 'Checked': False, 'Enable': True,
                'Visible': True, 'ForegroundColor': (0.0, 0.0, 0.0), 'Position': 1.0, **_ACTIVE}
    ALIASES = {'Text': 'Label', 'MenuSelectedFcn': 'Callback'}
    SHOWN = ['Label', 'Accelerator', 'Callback', 'Checked', 'Enable', 'Separator']

    def siblings(self):
        return [c for c in reversed(self.parent.children) if c.valid and c.TYPE == 'uimenu'] if self.parent is not None else [self]

    def get_value(self, k):
        if k == 'Position':
            return float(self.siblings().index(self) + 1)
        return super().get_value(k)

    def set_value(self, k, value):
        if k == 'Position':
            sib = self.siblings()
            n = int(round(float(np.asarray(value, float).reshape(-1)[0])))
            if n < 1:
                raise gerr('Position must be a positive integer.')
            sib.remove(self)
            sib.insert(min(n - 1, len(sib)), self)
            # children are kept newest first
            others = [c for c in self.parent.children if c not in sib]
            self.parent.children[:] = list(reversed(sib)) + others
            return
        if k == 'Accelerator':
            self.props[k] = py_str(value)[:1]
            return
        super().set_value(k, value)


class UIContextMenu(GObj):
    TYPE = 'uicontextmenu'
    CLASSNAME = 'matlab.ui.container.ContextMenu'
    DEFAULTS = {'Callback': '', 'Visible': False, 'Position': lambda: np.array([[0.0, 0.0]]), **_ACTIVE}
    ALIASES = {'ContextMenuOpeningFcn': 'Callback'}
    SHOWN = ['Callback', 'Visible']


class UIToolbar(GObj):
    TYPE = 'uitoolbar'
    CLASSNAME = 'matlab.ui.container.Toolbar'
    DEFAULTS = {'Visible': True, 'BackgroundColor': (0.94, 0.94, 0.94), **_ACTIVE}
    SHOWN = ['Visible', 'Tag']


class UIPushTool(GObj):
    TYPE = 'uipushtool'
    CLASSNAME = 'matlab.ui.container.toolbar.PushTool'
    DEFAULTS = {'CData': lambda: EMPTY(), 'ClickedCallback': '', 'TooltipString': '', 'Separator': False, 'Enable': True,
                'Visible': True, **_ACTIVE}
    ALIASES = {'Tooltip': 'TooltipString'}
    SHOWN = ['CData', 'ClickedCallback', 'TooltipString', 'Separator', 'Enable']

    def set_value(self, k, value):
        if k == 'CData':
            self.props[k] = np.asarray(value.a if type(value) is Char else value)
            return
        super().set_value(k, value)


class UIToggleTool(UIPushTool):
    TYPE = 'uitoggletool'
    CLASSNAME = 'matlab.ui.container.toolbar.ToggleTool'
    DEFAULTS = {**UIPushTool.DEFAULTS, 'State': False, 'OnCallback': '', 'OffCallback': ''}
    SHOWN = ['CData', 'State', 'ClickedCallback', 'OnCallback', 'OffCallback', 'TooltipString']


register(UIControl, UIPanel, UIButtonGroup, UITable, UITabGroup, UITab, UIMenu, UIContextMenu, UIToolbar, UIPushTool, UIToggleTool)

KINDS = {'uicontrol': UIControl, 'uipanel': UIPanel, 'uibuttongroup': UIButtonGroup, 'uitable': UITable,
         'uitabgroup': UITabGroup, 'uitab': UITab, 'uimenu': UIMenu, 'uicontextmenu': UIContextMenu,
         'uitoolbar': UIToolbar, 'uipushtool': UIPushTool, 'uitoggletool': UIToggleTool}


# ---- the description the page builds -------------------------------------------------------------

def icon_json(cd):
    """An icon's colours (m x n x 3 in 0..1, or uint8) for the page; NaN shows
    what is behind. None when there is none."""
    if cd is None or not numel(cd):
        return None
    a = np.asarray(cd)
    if a.dtype == np.uint8:
        a = a.astype(float) / 255.0
    elif a.dtype.kind in 'iu':
        a = a.astype(float) / float(np.iinfo(a.dtype).max)
    a = np.asarray(a, float)
    if a.ndim == 2:
        a = np.repeat(a[:, :, None], 3, axis=2)
    if a.ndim != 3 or a.shape[2] != 3 or a.shape[0] > 256 or a.shape[1] > 256:
        return None
    # RGBA bytes, row by row: four bytes a pixel, where floats would take 24
    rgba = np.zeros(a.shape[:2] + (4,), np.uint8)
    seen = ~np.isnan(a).any(axis=2)
    rgba[..., :3] = np.round(np.clip(np.nan_to_num(a), 0, 1) * 255).astype(np.uint8)
    rgba[..., 3] = np.where(seen, 255, 0)
    import base64
    return {'rgba': base64.b64encode(rgba.tobytes()).decode('ascii'), 'w': int(a.shape[1]), 'h': int(a.shape[0])}


def _font(p):
    return {'fontSize': float(p.get('FontSize', 8.0)), 'fontUnits': p.get('FontUnits', 'points'), 'fontName': p.get('FontName', 'Helvetica'),
            'fontWeight': p.get('FontWeight', 'normal'), 'fontAngle': p.get('FontAngle', 'normal')}


def _enable(v):
    return 'inactive' if v == 'inactive' else ('on' if v else 'off')


def _placed(c):
    p = c.props
    d = {'id': c.id, 'type': c.TYPE, 'units': p.get('Units', 'normalized'),
         'pos': [float(x) for x in _pos(c)] if 'Position' in p else [0.0, 0.0, 1.0, 1.0],
         'visible': bool(p.get('Visible', True)), 'tag': p.get('Tag', '')}
    d.update(_interact_json(c))
    return d


def _cell_text(x):
    t = type(x)
    if t in (Char, Str):
        return py_str(x)
    if t is bool or (isinstance(x, np.ndarray) and x.dtype == bool and x.size == 1):
        return bool(np.asarray(x).reshape(-1)[0])
    try:
        a = np.asarray(x, float).reshape(-1)
    except Exception:
        return ''
    if a.size == 0:
        return ''
    return jnum(a[0])


def _names(v, n):
    """ColumnName or RowName for the page: a list, 'numbered', or []."""
    if isinstance(v, str):
        return v
    if v is None or not numel(v):
        return []
    return lines_of(v)


def control_json(c):
    p = c.props
    t = c.TYPE
    if t == 'uigridlayout':
        px = getattr(c, 'px', None) or [0.0, 0.0, *inner_px(c.parent)]
        d = {'id': c.id, 'type': t, 'units': 'pixels', 'pos': [float(x) for x in px], 'visible': bool(p.get('Visible', True)),
             'tag': p.get('Tag', ''), 'bg': [float(x) for x in p['BackgroundColor']]}
        d['children'] = [control_json(k) for k in reversed(c.children) if k.valid and k.TYPE in CONTROLS]
        return d
    d = _placed(c)
    if t == 'uicomp':
        from .uiapp import comp_json
        return comp_json(c, d)
    if t == 'uicontrol':
        d.update(style=p['Style'], string=c.lines(), value=[jnum(v) for v in c.selected()], min=jnum(p['Min']), max=jnum(p['Max']),
                 bg=_color(p['BackgroundColor']), fg=_color(p['ForegroundColor']), halign=p['HorizontalAlignment'],
                 enable=_enable(p['Enable']), tip=p['TooltipString'], step=[float(x) for x in p['SliderStep'].reshape(-1)],
                 top=float(p['ListboxTop']), cdata=icon_json(p['CData']), cb=has_callback(p['Callback']),
                 kpf=has_callback(p['KeyPressFcn']), **_font(p))
        return d
    if t in ('uipanel', 'uibuttongroup'):
        d.update(title=p['Title'], titlePos=p['TitlePosition'], border=p['BorderType'], borderWidth=float(p['BorderWidth']),
                 bg=_color(p['BackgroundColor']), fg=_color(p['ForegroundColor']), **_font(p))
    elif t == 'uitabgroup':
        sel = c.selection()
        d.update(selected=sel.id if sel is not None else None, location=p['TabLocation'],
                 tabs=[dict(id=tab.id, title=tab.props['Title'], bg=_color(tab.props['BackgroundColor']), fg=_color(tab.props['ForegroundColor']),
                            tip=tab.props['TooltipString'], children=[control_json(k) for k in reversed(tab.children) if k.valid and k.TYPE in CONTROLS])
                       for tab in c.tabs()])
        return d
    elif t == 'uitable':
        data = p['Data']
        if type(data) is Cell:
            rows = [[_cell_text(x) for x in row] for row in data.a]
        else:
            a = np.asarray(data)
            if a.ndim < 2:
                a = a.reshape(1, -1)
            rows = [[bool(x) if a.dtype == bool else jnum(x) for x in row] for row in a] if a.size else []
        ed = p['ColumnEditable']
        d.update(data=rows, columnName=_names(p['ColumnName'], 0), rowName=_names(p['RowName'], 0),
                 columnWidth=p['ColumnWidth'] if isinstance(p['ColumnWidth'], str) else [x if isinstance(x, str) else jnum(x) for x in lines_or_numbers(p['ColumnWidth'])],
                 editable=[bool(x) for x in np.asarray(ed, bool).reshape(-1)] if numel(ed) else [],
                 formats=lines_of(p['ColumnFormat']) if numel(p['ColumnFormat']) else [],
                 bg=[_color(tuple(float(v) for v in r)) for r in np.asarray(p['BackgroundColor'], float).reshape(-1, 3)],
                 fg=_color(p['ForegroundColor']), striping=bool(p['RowStriping']), enable=_enable(p['Enable']),
                 tip=p['TooltipString'], edit=has_callback(p['CellEditCallback']), select=has_callback(p['CellSelectionCallback']),
                 kpf=has_callback(p['KeyPressFcn']), **_font(p))
        return d
    d['children'] = [control_json(k) for k in reversed(c.children) if k.valid and k.TYPE in CONTROLS]
    return d


def lines_or_numbers(v):
    if type(v) is Cell:
        out = []
        for x in v.a.reshape(-1, order='F'):
            out.append(py_str(x) if type(x) in (Char, Str) else float(np.asarray(x, float).reshape(-1)[0]))
        return out
    return [float(x) for x in np.asarray(v, float).reshape(-1)]


def menu_json(m):
    p = m.props
    return {'id': m.id, 'label': p['Label'], 'accel': p['Accelerator'], 'sep': bool(p['Separator']), 'checked': bool(p['Checked']),
            'enable': bool(p['Enable']), 'visible': bool(p['Visible']), 'color': _color(p['ForegroundColor']),
            'cb': has_callback(p['Callback']), 'tag': p['Tag'],
            'items': [menu_json(c) for c in reversed(m.children) if c.valid and c.TYPE == 'uimenu']}


def tool_json(t):
    p = t.props
    return {'id': t.id, 'kind': 'toggle' if t.TYPE == 'uitoggletool' else 'push', 'cdata': icon_json(p['CData']),
            'tip': p['TooltipString'], 'sep': bool(p['Separator']), 'enable': bool(p['Enable']), 'visible': bool(p['Visible']),
            'state': bool(p.get('State', False)), 'tag': p['Tag']}


FLAGS = {'wbdf': 'WindowButtonDownFcn', 'wbuf': 'WindowButtonUpFcn', 'wbmf': 'WindowButtonMotionFcn', 'scroll': 'WindowScrollWheelFcn',
         'kpf': 'KeyPressFcn', 'krf': 'KeyReleaseFcn', 'wkpf': 'WindowKeyPressFcn', 'wkrf': 'WindowKeyReleaseFcn',
         'bdf': 'ButtonDownFcn', 'size': 'SizeChangedFcn', 'resize': 'ResizeFcn'}


def _axes_inside(c):
    """Axes in a container and the containers in it (the shown tab's only)."""
    out = []
    kids = list(reversed(c.children))
    if c.TYPE == 'uitabgroup':
        sel = c.selection()
        kids = [sel] if sel is not None else []
    for k in kids:
        if not k.valid:
            continue
        if k.TYPE == 'axes' and k.yy_owner is None:
            out.append(k)
        elif k.TYPE in ('uipanel', 'uibuttongroup', 'uitabgroup', 'uitab', 'uigridlayout'):
            out += _axes_inside(k)
    return out


def layout_grids(o):
    """The grid layouts in o (a figure or container) place their children:
    each child's Position set to its cell, in pixels from the grid's lower
    left; axes keep a margin for their ticks and labels."""
    for c in list(o.children):
        if not c.valid:
            continue
        if c.TYPE == 'uigridlayout':
            if o.TYPE != 'uigridlayout':
                w, h = inner_px(o)
                c.px = [0.0, 0.0, float(w), float(h)]
            places = c.place(c.px[2], c.px[3])
            for k in c.kids():
                r = places.get(k.id)
                if r is None:
                    continue
                if k.TYPE == 'uigridlayout':
                    k.px = [float(x) for x in r]
                elif k.TYPE == 'axes':
                    k.props['Units'] = 'pixels'
                    k.props['Position'] = np.array([[r[0] + 45.0, r[1] + 38.0, max(1.0, r[2] - 60.0), max(1.0, r[3] - 66.0)]])
                else:
                    k.props['Units'] = 'pixels'
                    k.props['Position'] = np.array([r], float)
            layout_grids(c)
        elif c.TYPE in ('uipanel', 'uibuttongroup', 'uitab', 'uitabgroup'):
            layout_grids(c)


def serialize_ui(f, d):
    """The figure's controls, menus, context menus and toolbars, and what its
    callbacks want to hear about, added to the description d."""
    p = f.props
    crf = p['CloseRequestFcn']
    d.update(menuBar=str(p['MenuBar']).lower(), toolBar=str(p['ToolBar']).lower(), pointer=p['Pointer'], resize=bool(p['Resize']),
             dialog=f.is_dialog, placed=bool(getattr(f, 'placed', False)),
             closeDefault=isinstance(crf, str) and crf.strip().rstrip(';').replace('()', '') == 'closereq',
             flags={k: has_callback(p[v]) for k, v in FLAGS.items()},
             cmenu=p['UIContextMenu'].id if p['UIContextMenu'] is not None and p['UIContextMenu'].valid else None)
    layout_grids(f)
    kids = [c for c in reversed(f.children) if c.valid]
    d['menus'] = [menu_json(m) for m in kids if m.TYPE == 'uimenu']
    d['toolbars'] = [{'id': tb.id, 'visible': bool(tb.props['Visible']),
                      'tools': [tool_json(t) for t in reversed(tb.children) if t.valid and t.TYPE in ('uipushtool', 'uitoggletool')]}
                     for tb in kids if tb.TYPE == 'uitoolbar']
    d['controls'] = [control_json(c) for c in kids if c.TYPE in CONTROLS]
    d['cmenus'] = [{'id': m.id, 'cb': has_callback(m.props['Callback']),
                    'items': [menu_json(c) for c in reversed(m.children) if c.valid and c.TYPE == 'uimenu']}
                   for m in kids if m.TYPE == 'uicontextmenu']
    for c in kids:
        if c.TYPE in ('uipanel', 'uibuttongroup', 'uitabgroup', 'uigridlayout'):
            for ax in _axes_inside(c):
                d['axes'].append(serialize_axes(ax))
    if p['Units'] == 'normalized' or p['Units'] not in ('pixels',):
        w, h = inner_px(f)
        d['width'], d['height'] = float(w), float(h)
