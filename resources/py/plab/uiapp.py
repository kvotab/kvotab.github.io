"""The components of apps (uifigure and its kin): buttons, labels, edit
fields, text areas, drop-downs, list boxes, check boxes, switches, sliders,
spinners, knobs, gauges, lamps, state, radio and toggle buttons, images and
hyperlinks; and the grid layout that places what it holds.

Each kind is a class of its own (UIComp's subclasses, made from KINDS),
with its properties and their defaults, its class name and Type. Values
are checked as they are set (a numeric field within its Limits, a
drop-down's Value among its Items). The page draws them (pylab-ui.js) and
reports pushes and changed values, which set Value and queue the
callbacks with their event data (uievents.py calls component_event).
"""
import math

import numpy as np

from .values import MError, Char, Cell, Str, Struct, FH, EMPTY, numel, py_str
from .graphics_base import GObj, to_color, gerr, register, HArr
from .uiobjects import _Placed, UIButtonGroup, jnum

_COMMON = {'Position': lambda: np.array([[100.0, 100.0, 100.0, 22.0]]), 'Units': 'pixels', 'Visible': True, 'Enable': True,
           'Tooltip': '', 'Tag': '', 'UserData': lambda: EMPTY(), 'FontName': 'Helvetica', 'FontSize': 12.0, 'FontWeight': 'normal',
           'FontAngle': 'normal', 'FontColor': (0.0, 0.0, 0.0), 'BackgroundColor': (0.96, 0.96, 0.96), 'HorizontalAlignment': 'center',
           'Layout': None, 'ContextMenu': None, 'HandleVisibility': 'on', 'BusyAction': 'queue', 'Interruptible': True,
           'CreateFcn': '', 'DeleteFcn': ''}

# kind: (Type, class name, defaults)
KINDS = {
    'button': ('uibutton', 'Button', {'Text': 'Button', 'Icon': '', 'IconAlignment': 'left', 'ButtonPushedFcn': '', 'WordWrap': False,
                                      'VerticalAlignment': 'center'}),
    'statebutton': ('uistatebutton', 'StateButton', {'Text': 'State Button', 'Value': False, 'Icon': '', 'ValueChangedFcn': ''}),
    'label': ('uilabel', 'Label', {'Text': 'Label', 'VerticalAlignment': 'center', 'WordWrap': False, 'Interpreter': 'none',
                                   'BackgroundColor': 'none', 'Position': lambda: np.array([[100.0, 100.0, 31.0, 22.0]])}),
    'editfield': ('uieditfield', 'EditField', {'Value': lambda: Char.of(''), 'Placeholder': '', 'Editable': True,
                                               'ValueChangedFcn': '', 'ValueChangingFcn': '', 'BackgroundColor': (1.0, 1.0, 1.0),
                                               'HorizontalAlignment': 'left', 'CharacterLimits': lambda: np.array([[0.0, np.inf]])}),
    'numericeditfield': ('uinumericeditfield', 'NumericEditField',
                         {'Value': 0.0, 'Limits': lambda: np.array([[-np.inf, np.inf]]), 'LowerLimitInclusive': True, 'UpperLimitInclusive': True,
                          'RoundFractionalValues': False, 'ValueDisplayFormat': '%11.4g', 'Editable': True, 'ValueChangedFcn': '',
                          'ValueChangingFcn': '', 'BackgroundColor': (1.0, 1.0, 1.0), 'HorizontalAlignment': 'right', 'Placeholder': ''}),
    'textarea': ('uitextarea', 'TextArea', {'Value': lambda: Cell.of_list([Char.of('')], (1, 1)), 'Editable': True, 'WordWrap': True,
                                            'ValueChangedFcn': '', 'ValueChangingFcn': '', 'BackgroundColor': (1.0, 1.0, 1.0),
                                            'HorizontalAlignment': 'left', 'Placeholder': '',
                                            'Position': lambda: np.array([[100.0, 100.0, 150.0, 60.0]])}),
    'dropdown': ('uidropdown', 'DropDown', {'Items': lambda: _cells(['Option 1', 'Option 2', 'Option 3', 'Option 4']), 'ItemsData': lambda: EMPTY(),
                                            'Value': lambda: Char.of('Option 1'), 'Editable': False, 'ValueChangedFcn': '', 'Placeholder': '',
                                            'BackgroundColor': (0.96, 0.96, 0.96), 'ClickedFcn': '', 'DropDownOpeningFcn': ''}),
    'listbox': ('uilistbox', 'ListBox', {'Items': lambda: _cells(['Item 1', 'Item 2', 'Item 3', 'Item 4']), 'ItemsData': lambda: EMPTY(),
                                         'Value': lambda: Char.of('Item 1'), 'Multiselect': False, 'ValueChangedFcn': '', 'ClickedFcn': '',
                                         'DoubleClickedFcn': '', 'BackgroundColor': (1.0, 1.0, 1.0), 'HorizontalAlignment': 'left',
                                         'Position': lambda: np.array([[100.0, 100.0, 100.0, 74.0]])}),
    'checkbox': ('uicheckbox', 'CheckBox', {'Text': 'Check Box', 'Value': False, 'ValueChangedFcn': '', 'WordWrap': False,
                                            'Position': lambda: np.array([[100.0, 100.0, 84.0, 22.0]])}),
    'switch': ('uiswitch', 'Switch', {'Items': lambda: _cells(['Off', 'On']), 'ItemsData': lambda: EMPTY(), 'Value': lambda: Char.of('Off'),
                                      'Orientation': 'horizontal', 'ValueChangedFcn': '', 'Style': 'slider',
                                      'Position': lambda: np.array([[100.0, 100.0, 45.0, 20.0]])}),
    'slider': ('uislider', 'Slider', {'Value': 0.0, 'Limits': lambda: np.array([[0.0, 100.0]]), 'MajorTicks': lambda: np.array([[0, 20, 40, 60, 80, 100.0]]),
                                      'MajorTicksMode': 'auto', 'MajorTickLabels': None, 'MinorTicks': lambda: np.arange(0, 101, 5.0).reshape(1, -1),
                                      'Orientation': 'horizontal', 'ValueChangedFcn': '', 'ValueChangingFcn': '', 'Step': 0.0,
                                      'Position': lambda: np.array([[100.0, 100.0, 150.0, 3.0]])}),
    'spinner': ('uispinner', 'Spinner', {'Value': 0.0, 'Limits': lambda: np.array([[-np.inf, np.inf]]), 'Step': 1.0, 'LowerLimitInclusive': True,
                                         'UpperLimitInclusive': True, 'RoundFractionalValues': False, 'ValueDisplayFormat': '%11.4g',
                                         'Editable': True, 'ValueChangedFcn': '', 'ValueChangingFcn': '', 'BackgroundColor': (1.0, 1.0, 1.0),
                                         'HorizontalAlignment': 'right'}),
    'knob': ('uiknob', 'Knob', {'Value': 0.0, 'Limits': lambda: np.array([[0.0, 100.0]]), 'MajorTicks': lambda: np.array([[0, 20, 40, 60, 80, 100.0]]),
                                'MajorTicksMode': 'auto', 'MajorTickLabels': None, 'ValueChangedFcn': '', 'ValueChangingFcn': '', 'Style': 'continuous',
                                'Position': lambda: np.array([[100.0, 100.0, 60.0, 60.0]])}),
    'discreteknob': ('uidiscreteknob', 'DiscreteKnob', {'Items': lambda: _cells(['Off', 'Low', 'Medium', 'High']), 'ItemsData': lambda: EMPTY(),
                                                        'Value': lambda: Char.of('Off'), 'ValueChangedFcn': '',
                                                        'Position': lambda: np.array([[100.0, 100.0, 60.0, 60.0]])}),
    'gauge': ('uigauge', 'Gauge', {'Value': 0.0, 'Limits': lambda: np.array([[0.0, 100.0]]), 'MajorTicks': lambda: np.array([[0, 20, 40, 60, 80, 100.0]]),
                                   'MajorTicksMode': 'auto', 'MajorTickLabels': None, 'ScaleColors': lambda: EMPTY(), 'ScaleColorLimits': lambda: EMPTY(),
                                   'ScaleDirection': 'clockwise', 'Style': 'circular', 'BackgroundColor': (1.0, 1.0, 1.0),
                                   'Position': lambda: np.array([[100.0, 100.0, 120.0, 120.0]])}),
    'lamp': ('uilamp', 'Lamp', {'Color': (0.0, 1.0, 0.0), 'Position': lambda: np.array([[100.0, 100.0, 20.0, 20.0]])}),
    'radiobutton': ('uiradiobutton', 'RadioButton', {'Text': 'Button', 'Value': False, 'Position': lambda: np.array([[10.0, 10.0, 58.0, 22.0]])}),
    'togglebutton': ('uitogglebutton', 'ToggleButton', {'Text': 'Button', 'Value': False, 'Icon': '',
                                                        'Position': lambda: np.array([[10.0, 10.0, 100.0, 22.0]])}),
    'image': ('uiimage', 'Image', {'ImageSource': '', 'ScaleMethod': 'fit', 'HorizontalAlignment': 'center', 'VerticalAlignment': 'center',
                                   'ImageClickedFcn': '', 'URL': '', 'AltText': '', 'BackgroundColor': 'none',
                                   'Position': lambda: np.array([[100.0, 100.0, 100.0, 100.0]])}),
    'hyperlink': ('uihyperlink', 'Hyperlink', {'Text': 'Hyperlink', 'URL': '', 'HyperlinkClickedFcn': '', 'VisitedColor': (0.5, 0.18, 0.56),
                                               'FontColor': (0.0, 0.33, 0.8), 'BackgroundColor': 'none', 'HorizontalAlignment': 'left',
                                               'Position': lambda: np.array([[100.0, 100.0, 70.0, 22.0]])}),
}
_CALLBACKS = ('ButtonPushedFcn', 'ValueChangedFcn', 'ValueChangingFcn', 'ImageClickedFcn', 'HyperlinkClickedFcn', 'ClickedFcn',
              'DoubleClickedFcn', 'DropDownOpeningFcn', 'CreateFcn', 'DeleteFcn')


def _cells(items):
    return Cell.of_list([Char.of(s) for s in items], (1, len(items)))


def _items(v):
    if type(v) is Cell:
        return [py_str(x) for x in v.a.reshape(-1, order='F')]
    if type(v) is Str:
        return [s or '' for s in v.a.reshape(-1, order='F')]
    if type(v) is Char:
        return v.row_strs() if v.a.shape[0] > 1 else [v.str()]
    return []


class UIComp(_Placed):
    """A component of an app; KIND says which."""
    TYPE = 'uicomp'
    KIND = ''
    UITYPE = ''
    CLASSNAME = 'matlab.ui.control.Component'
    DEFAULTS = dict(_COMMON)

    def getprop(self, name):
        if name.lower() == 'type':
            return Char.of(self.UITYPE)
        return super().getprop(name)

    def get_value(self, k):
        if k == 'Layout':
            v = self.props.get('Layout')
            if v is None:
                v = Struct.scalar({'Row': EMPTY(), 'Column': EMPTY()})
            return v
        if k == 'Value' and isinstance(self.props.get('Value'), bool):
            # a logical Value stays logical (never 'on' or 'off')
            return self.props['Value']
        if k == 'Position' and self.parent is not None and self.parent.TYPE == 'uigridlayout':
            # a grid's child is where the grid puts it
            from .uiobjects import layout_grids
            f = self.figure()
            if f is not None:
                layout_grids(f)
        return super().get_value(k)

    def set_value(self, k, value):
        kind = self.KIND
        if k in ('Enable', 'Visible', 'Editable', 'Multiselect', 'WordWrap', 'RoundFractionalValues', 'LowerLimitInclusive', 'UpperLimitInclusive'):
            self.props[k] = _onoff(value)
            self.touch()
            return
        if k in ('Text', 'Placeholder', 'Tooltip', 'URL', 'ValueDisplayFormat', 'AltText'):
            self.props[k] = py_str(value) if not (type(value) is Cell) else '\n'.join(_items(value))
            self.touch()
            return
        if k in ('FontColor', 'Color', 'VisitedColor'):
            self.props[k] = to_color(value)
            self.touch()
            return
        if k == 'BackgroundColor':
            self.props[k] = to_color(value, ('none',))
            self.touch()
            return
        if k in ('FontSize', 'Step'):
            self.props[k] = float(np.asarray(value, float).reshape(-1)[0])
            self.touch()
            return
        if k in ('HorizontalAlignment', 'VerticalAlignment', 'FontWeight', 'FontAngle', 'Orientation', 'ScaleMethod', 'IconAlignment',
                 'ScaleDirection', 'Interpreter'):
            self.props[k] = py_str(value).lower()
            self.touch()
            return
        if k == 'Limits':
            a = np.asarray(value, float).reshape(-1)
            if a.size != 2 or not a[0] < a[1]:
                raise gerr("'Limits' must be a 1-by-2 vector of increasing numbers.", 'MATLAB:ui:Limits')
            self.props[k] = a.reshape(1, 2)
            if 'MajorTicks' in self.props and self.props.get('MajorTicksMode', 'auto') == 'auto' and np.all(np.isfinite(a)):
                # ticks not set by hand follow the limits
                major, minor = _nice_ticks(a[0], a[1])
                self.props['MajorTicks'] = major.reshape(1, -1)
                if 'MinorTicks' in self.props and self.props.get('MinorTicksMode', 'auto') == 'auto':
                    self.props['MinorTicks'] = minor.reshape(1, -1)
            v = self.props.get('Value')
            if isinstance(v, float) and kind in ('slider', 'knob', 'spinner', 'numericeditfield'):
                self.props['Value'] = float(min(max(v, a[0]), a[1]))
            self.touch()
            return
        if k in ('MajorTicks', 'MinorTicks', 'ScaleColorLimits'):
            self.props[k] = np.asarray(value, float).reshape(1, -1) if numel(value) else EMPTY()
            if k in ('MajorTicks', 'MinorTicks'):
                self.props[k + 'Mode'] = 'manual'
            self.touch()
            return
        if k == 'MajorTickLabels':
            self.props[k] = _items(value)
            self.touch()
            return
        if k == 'ScaleColors':
            self.props[k] = value
            self.touch()
            return
        if k == 'Items':
            items = _items(value)
            self.props[k] = _cells(items)
            if kind in ('dropdown', 'listbox', 'switch', 'discreteknob'):
                vals = self._values()
                cur = self.props.get('Value')
                if kind == 'listbox' and self.props.get('Multiselect'):
                    pass
                elif not any(_same(cur, x) for x in vals) and vals:
                    self.props['Value'] = vals[0]
            self.touch()
            return
        if k == 'ItemsData':
            self.props[k] = value
            vals = self._values()
            if vals and not any(_same(self.props.get('Value'), x) for x in vals):
                self.props['Value'] = vals[0]
            self.touch()
            return
        if k == 'Value':
            self.props['Value'] = self._check_value(value)
            self.touch()
            return
        if k == 'Layout':
            if type(value) is not Struct:
                raise gerr("'Layout' takes the layout options of a grid: Row and Column.", 'MATLAB:ui:Layout')
            self.props['Layout'] = value
            if self.parent is not None and self.parent.TYPE == 'uigridlayout':
                self.parent.touch()
            self.touch()
            return
        if k == 'ImageSource':
            self.props[k] = value
            self.touch()
            return
        if k in _CALLBACKS:
            self.props[k] = value
            return
        super().set_value(k, value)

    def _values(self):
        """What Value may be: the ItemsData, or the Items."""
        d = self.props.get('ItemsData')
        if d is not None and numel(d):
            if type(d) is Cell:
                return list(d.a.reshape(-1, order='F'))
            return [float(x) for x in np.asarray(d, float).reshape(-1)]
        return [Char.of(s) for s in _items(self.props.get('Items'))]

    def _check_value(self, v):
        kind = self.KIND
        if kind in ('statebutton', 'checkbox', 'radiobutton', 'togglebutton'):
            b = _onoff(v)
            if kind in ('radiobutton', 'togglebutton') and b and self.parent is not None and self.parent.TYPE == 'uibuttongroup':
                for o in self.parent.buttons():
                    if o is not self and getattr(o, 'KIND', '') in ('radiobutton', 'togglebutton'):
                        o.props['Value'] = False
            return b
        if kind == 'editfield':
            return Char.of(py_str(v))
        if kind == 'textarea':
            if type(v) is Cell:
                return Cell.of_list([Char.of(py_str(x)) for x in v.a.reshape(-1, order='F')], (v.a.size, 1))
            lines = _items(v)
            return Cell.of_list([Char.of(s) for s in lines] or [Char.of('')], (max(1, len(lines)), 1))
        if kind in ('numericeditfield', 'spinner', 'slider', 'knob', 'gauge'):
            try:
                x = float(np.asarray(v, float).reshape(-1)[0])
            except (TypeError, ValueError, IndexError):
                raise gerr("'Value' must be a number.", 'MATLAB:ui:Value')
            lo, hi = (float(t) for t in np.asarray(self.props['Limits'], float).reshape(-1))
            if kind == 'gauge':
                return x
            if not (lo <= x <= hi):
                raise gerr(f"'Value' must be within the Limits [{lo:g} {hi:g}].", 'MATLAB:ui:ValueOutsideLimits')
            if self.props.get('RoundFractionalValues'):
                x = float(np.round(x))
            return x
        if kind in ('dropdown', 'switch', 'discreteknob'):
            vals = self._values()
            if kind == 'dropdown' and self.props.get('Editable') and is_text(v):
                return Char.of(py_str(v))
            for x in vals:
                if _same(v, x):
                    return x
            raise gerr("'Value' must be an element of 'Items' (or of 'ItemsData' when it is set).", 'MATLAB:ui:ValueNotInItems')
        if kind == 'listbox':
            vals = self._values()
            if self.props.get('Multiselect'):
                want = list(v.a.reshape(-1, order='F')) if type(v) is Cell else ([v] if numel(v) else [])
                chosen = [x for x in vals if any(_same(w, x) for w in want)]
                if len(chosen) != len(want):
                    raise gerr("Each element of 'Value' must be an element of 'Items'.", 'MATLAB:ui:ValueNotInItems')
                return Cell.of_list(chosen, (1, len(chosen))) if chosen and type(chosen[0]) is Char else (np.array([chosen], float) if chosen else EMPTY())
            if not numel(v):
                return EMPTY()
            for x in vals:
                if _same(v, x):
                    return x
            raise gerr("'Value' must be an element of 'Items' (or of 'ItemsData' when it is set).", 'MATLAB:ui:ValueNotInItems')
        return v


def is_text(v):
    return type(v) in (Char, Str)


def _same(a, b):
    if is_text(a) and is_text(b):
        return py_str(a) == py_str(b)
    if is_text(a) or is_text(b):
        return False
    try:
        return float(np.asarray(a, float).reshape(-1)[0]) == float(np.asarray(b, float).reshape(-1)[0])
    except (TypeError, ValueError, IndexError):
        return a is b


def _onoff(v):
    if is_text(v):
        s = py_str(v).lower()
        if s in ('on', 'true'):
            return True
        if s in ('off', 'false'):
            return False
        raise gerr(f"'{py_str(v)}' is not 'on' or 'off'.", 'MATLAB:ui:OnOff')
    return bool(np.all(np.asarray(v)))


CLASSES = {}
for _kind, (_t, _cn, _d) in KINDS.items():
    _cls = type('UI' + _cn, (UIComp,), {'KIND': _kind, 'UITYPE': _t, 'CLASSNAME': 'matlab.ui.control.' + _cn,
                                         'DEFAULTS': {**_COMMON, **_d}})
    CLASSES[_kind] = _cls
register(*CLASSES.values())


# radio and toggle buttons of apps in a button group: a logical Value
_orig_buttons = UIButtonGroup.buttons
_orig_selection = UIButtonGroup.selection
_orig_select = UIButtonGroup.select


def _buttons(self):
    return [c for c in reversed(self.children) if c.valid and (
        (c.TYPE == 'uicontrol' and c.props['Style'] in ('radiobutton', 'togglebutton')) or
        (c.TYPE == 'uicomp' and c.KIND in ('radiobutton', 'togglebutton')))]


def _selection(self):
    for b in self.buttons():
        if b.TYPE == 'uicomp':
            if b.props['Value']:
                return b
        elif b.selected() == [b.props['Max']]:
            return b
    return None


def _select(self, b):
    for x in self.buttons():
        if x.TYPE == 'uicomp':
            x.props['Value'] = x is b
        else:
            x.props['Value'] = x.props['Max'] if x is b else x.props['Min']
    self.touch()


UIButtonGroup.buttons = _buttons
UIButtonGroup.selection = _selection
UIButtonGroup.select = _select


# ---- the grid layout -----------------------------------------------------------------------------------------------

class UIGridLayout(GObj):
    """uigridlayout: rows and columns that place what it holds, filling its parent."""
    TYPE = 'uigridlayout'
    CLASSNAME = 'matlab.ui.container.GridLayout'
    DEFAULTS = {'RowHeight': lambda: _cells(['1x', '1x']), 'ColumnWidth': lambda: _cells(['1x', '1x']),
                'Padding': lambda: np.array([[10.0, 10.0, 10.0, 10.0]]), 'RowSpacing': 10.0, 'ColumnSpacing': 10.0,
                'BackgroundColor': (0.94, 0.94, 0.94), 'Visible': True, 'Scrollable': False, 'Tag': '', 'UserData': lambda: EMPTY(),
                'Layout': None, 'HandleVisibility': 'on', 'CreateFcn': '', 'DeleteFcn': ''}

    def set_value(self, k, value):
        if k in ('RowHeight', 'ColumnWidth'):
            self.props[k] = _sizes(value)
            self.touch()
            return
        if k == 'Padding':
            a = np.asarray(value, float).reshape(-1)
            self.props[k] = (np.full(4, a[0]) if a.size == 1 else a).reshape(1, 4)
            self.touch()
            return
        if k in ('RowSpacing', 'ColumnSpacing'):
            self.props[k] = float(np.asarray(value, float).reshape(-1)[0])
            self.touch()
            return
        if k == 'Layout':
            self.props[k] = value
            self.touch()
            return
        if k == 'BackgroundColor':
            self.props[k] = to_color(value)
            self.touch()
            return
        super().set_value(k, value)

    def get_value(self, k):
        if k == 'Layout':
            v = self.props.get('Layout')
            return v if v is not None else Struct.scalar({'Row': EMPTY(), 'Column': EMPTY()})
        return super().get_value(k)

    def kids(self):
        return [c for c in reversed(self.children) if c.valid and c.TYPE in ('uicomp', 'uipanel', 'uibuttongroup', 'uitabgroup', 'axes',
                                                                                 'uigridlayout', 'uitable', 'uicontrol')]

    def cells(self):
        """Each child's (row span, column span), automatic places filling the rows in order."""
        rows = len(_items(self.props['RowHeight'])) if type(self.props['RowHeight']) is Cell else 1
        cols = len(_items(self.props['ColumnWidth'])) if type(self.props['ColumnWidth']) is Cell else 1
        taken = set()
        out = []
        auto = 0
        for c in self.kids():
            lay = c.props.get('Layout')
            r = cc = None
            if type(lay) is Struct:
                rv = np.asarray(lay.get1('Row'), float).reshape(-1) if numel(lay.get1('Row')) else None
                cv = np.asarray(lay.get1('Column'), float).reshape(-1) if numel(lay.get1('Column')) else None
                if rv is not None and cv is not None:
                    r = (int(rv.min()), int(rv.max()))
                    cc = (int(cv.min()), int(cv.max()))
            if r is None:
                while auto in taken:
                    auto += 1
                r = (auto // cols + 1,) * 2
                cc = (auto % cols + 1,) * 2
                c.props['Layout'] = Struct.scalar({'Row': float(r[0]), 'Column': float(cc[0])})
                auto += 1
            for i in range(r[0], r[1] + 1):
                for j in range(cc[0], cc[1] + 1):
                    taken.add((i - 1) * cols + (j - 1))
            out.append((c, r, cc))
        return out, max(rows, max((r[1] for _, r, _ in out), default=0)), cols

    def place(self, w, h):
        """Pixel positions [x y w h] from the lower left of the grid for each child."""
        placed, nrows, ncols = self.cells()
        pad = np.asarray(self.props['Padding'], float).reshape(-1)
        rh = _items(self.props['RowHeight']) + ['1x'] * max(0, nrows - len(_items(self.props['RowHeight'])))
        cw = _items(self.props['ColumnWidth']) + ['1x'] * max(0, ncols - len(_items(self.props['ColumnWidth'])))
        rs, cs = float(self.props['RowSpacing']), float(self.props['ColumnSpacing'])
        heights = _tracks(rh, h - pad[1] - pad[3] - rs * (nrows - 1), [22.0] * nrows)
        widths = _tracks(cw, w - pad[0] - pad[2] - cs * (ncols - 1), [100.0] * ncols)
        out = {}
        for c, r, cc in placed:
            x = pad[0] + sum(widths[:cc[0] - 1]) + cs * (cc[0] - 1)
            ww = sum(widths[cc[0] - 1:cc[1]]) + cs * (cc[1] - cc[0])
            top = pad[3] + sum(heights[:r[0] - 1]) + rs * (r[0] - 1)
            hh = sum(heights[r[0] - 1:r[1]]) + rs * (r[1] - r[0])
            out[c.id] = [x, h - top - hh, ww, hh]
        return out


def _sizes(v):
    if type(v) is Cell:
        items = []
        for x in v.a.reshape(-1, order='F'):
            items.append(Char.of(py_str(x)) if is_text(x) else Char.of(f'{float(np.asarray(x, float).reshape(-1)[0]):g}'))
        return Cell.of_list(items, (1, len(items)))
    if is_text(v):
        return _cells([py_str(v)])
    a = np.asarray(v, float).reshape(-1)
    return _cells([f'{x:g}' for x in a])


def _tracks(spec, total, fit):
    """Sizes of rows or columns: pixels as given, 'fit' as the content's, the
    rest shared by the weights of the 'nx' ones."""
    sizes = [0.0] * len(spec)
    weights = {}
    used = 0.0
    for i, s in enumerate(spec):
        s = s.strip().lower()
        if s.endswith('x'):
            try:
                weights[i] = float(s[:-1] or 1)
            except ValueError:
                weights[i] = 1.0
        elif s == 'fit':
            sizes[i] = fit[i] if i < len(fit) else 22.0
            used += sizes[i]
        else:
            try:
                sizes[i] = float(s)
            except ValueError:
                sizes[i] = 0.0
            used += sizes[i]
    left = max(0.0, total - used)
    wsum = sum(weights.values())
    for i, wgt in weights.items():
        sizes[i] = left * wgt / wsum if wsum else 0.0
    return sizes


register(UIGridLayout)


# ---- what the page is given ---------------------------------------------------------------------------------------------

def _color(c):
    if isinstance(c, str):
        return c
    return [float(x) for x in c] if c is not None else None


def comp_json(c, base):
    p = c.props
    kind = c.KIND
    d = dict(base)
    d.update(kind=kind, enable='on' if p['Enable'] else 'off', tip=p.get('Tooltip', ''), fontSize=float(p['FontSize']),
             fontName=p['FontName'], fontWeight=p['FontWeight'], fontAngle=p['FontAngle'], fg=_color(p['FontColor']),
             bg=_color(p['BackgroundColor']), halign=p.get('HorizontalAlignment', 'center'), valign=p.get('VerticalAlignment', 'center'))
    if 'Text' in p:
        d['text'] = p['Text']
    if 'Items' in p:
        d['items'] = _items(p['Items'])
        vals = c._values()
        v = p['Value']
        if kind == 'listbox' and p.get('Multiselect'):
            want = list(v.a.reshape(-1, order='F')) if type(v) is Cell else (list(np.asarray(v, float).reshape(-1)) if numel(v) else [])
            d['selected'] = [i for i, x in enumerate(vals) if any(_same(w, x) for w in want)]
        else:
            d['selected'] = [i for i, x in enumerate(vals) if _same(v, x)][:1]
            if kind == 'dropdown' and p.get('Editable') and not d['selected']:
                d['typed'] = py_str(v) if is_text(v) else ''
    v = p.get('Value')
    if kind in ('numericeditfield', 'spinner') and isinstance(v, float):
        from .builtins.fmt import sprintf
        try:
            d['display'] = sprintf(p.get('ValueDisplayFormat') or '%11.4g', [v]).strip()
        except Exception:
            d['display'] = f'{v:g}'
    if isinstance(v, bool):
        d['value'] = v
    elif isinstance(v, float):
        d['value'] = jnum(v)
    elif type(v) is Char:
        d['value'] = v.str()
    elif type(v) is Cell and kind == 'textarea':
        d['value'] = '\n'.join(_items(v))
    for k in ('Limits', 'MajorTicks', 'MinorTicks', 'ScaleColorLimits'):
        if k in p and numel(p[k]):
            d[k[0].lower() + k[1:]] = [jnum(x) for x in np.asarray(p[k], float).reshape(-1)]
    if p.get('MajorTickLabels') is not None:
        d['majorTickLabels'] = p['MajorTickLabels']
    for k in ('Placeholder', 'Editable', 'Multiselect', 'WordWrap', 'Orientation', 'Step', 'ValueDisplayFormat', 'URL', 'ScaleMethod',
              'Style', 'IconAlignment', 'ScaleDirection'):
        if k in p:
            d[k[0].lower() + k[1:]] = p[k]
    if 'Color' in p:
        d['color'] = _color(p['Color'])
    if 'ScaleColors' in p and numel(p['ScaleColors']):
        sc = p['ScaleColors']
        d['scaleColors'] = [_color(to_color(x)) for x in sc.a.reshape(-1)] if type(sc) is Cell else [list(map(float, r)) for r in np.asarray(sc, float).reshape(-1, 3)]
    if kind == 'image' or 'Icon' in p:
        src = p.get('ImageSource') if kind == 'image' else p.get('Icon')
        d['image'] = _image_url(src)
    d['cb'] = {k: _has(p.get(k)) for k in ('ValueChangingFcn', 'ImageClickedFcn', 'HyperlinkClickedFcn')}
    return d


def _has(v):
    from .graphics_base import has_callback
    return bool(has_callback(v)) if v is not None else False


def _image_url(src):
    """An image for the page: a data URL of the picture file or of an RGB array."""
    import base64
    import io
    import os
    if src is None or (isinstance(src, str) and not src) or (type(src) is Char and not src.str()):
        return None
    if is_text(src):
        from .builtins.iofun import abspath
        path = abspath(py_str(src))
        if not os.path.isfile(path):
            return None
        ext = os.path.splitext(path)[1].lower().lstrip('.')
        mime = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png', 'gif': 'gif', 'svg': 'svg+xml'}.get(ext)
        if mime is None:
            return None
        with open(path, 'rb') as fh:
            data = fh.read(4 * 1024 * 1024)
        return f'data:image/{mime};base64,' + base64.b64encode(data).decode('ascii')
    a = np.asarray(src)
    if a.ndim == 3 and a.shape[2] in (3, 4):
        import zlib
        import struct as st
        img = a if a.dtype == np.uint8 else np.clip(np.round(np.asarray(a, float) * 255), 0, 255).astype(np.uint8)
        h, w, ch = img.shape
        raw = b''.join(b'\x00' + img[i].tobytes() for i in range(h))

        def chunk(t, body):
            return st.pack('>I', len(body)) + t + body + st.pack('>I', zlib.crc32(t + body) & 0xffffffff)
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', st.pack('>2I5B', w, h, 8, 2 if ch == 3 else 6, 0, 0, 0)) + \
            chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')
        return 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')
    return None


def _nice_ticks(lo, hi):
    """About five major ticks over [lo, hi] at a step of 1, 2 or 5 times a power of ten (0:20:100 for [0 100]),
    and minor ones at a quarter of a step of 2, a fifth of a step of 1 or 5."""
    raw = (hi - lo) / 5
    p = 10.0 ** math.floor(math.log10(raw))
    m = next(m for m in (1, 2, 5, 10) if m * p >= raw * (1 - 1e-12))
    step = m * p
    ticks = lambda s: np.arange(math.ceil(lo / s - 1e-9), math.floor(hi / s + 1e-9) + 1) * s
    return ticks(step), ticks(step / (4 if m == 2 else 5))


def grid_json(g, base, w, h):
    d = dict(base)
    d.update(bg=_color(g.props['BackgroundColor']))
    return d


# ---- what the page reports ----------------------------------------------------------------------------------------------

def _from_page(c, raw):
    """A value as the page sends it, as the component holds it."""
    kind = c.KIND
    if kind in ('statebutton', 'checkbox', 'radiobutton', 'togglebutton'):
        return bool(raw)
    if kind in ('numericeditfield', 'spinner', 'slider', 'knob'):
        return float(raw)
    if kind == 'editfield':
        return Char.of(str(raw))
    if kind == 'textarea':
        lines = str(raw).split('\n')
        return Cell.of_list([Char.of(s) for s in lines], (len(lines), 1))
    if kind in ('dropdown', 'switch', 'discreteknob', 'listbox'):
        vals = c._values()
        if kind == 'dropdown' and isinstance(raw, str):
            return Char.of(raw)
        idx = [int(i) for i in (raw if isinstance(raw, list) else [raw])]
        chosen = [vals[i] for i in idx if 0 <= i < len(vals)]
        if kind == 'listbox' and c.props.get('Multiselect'):
            if chosen and type(chosen[0]) is Char:
                return Cell.of_list(chosen, (1, len(chosen)))
            return np.array([chosen], float) if chosen else EMPTY()
        return chosen[0] if chosen else c.props['Value']
    return raw


def component_event(c, fig, ev):
    from .uievents import queue, evdata
    a = ev.get('action')
    p = c.props
    if a == 'push':
        if c.KIND == 'button':
            queue(c, 'ButtonPushedFcn', evdata(c, 'ButtonPushed'))
        return
    if a == 'image':
        queue(c, 'ImageClickedFcn', evdata(c, 'ImageClicked'))
        return
    if a == 'link':
        queue(c, 'HyperlinkClickedFcn', evdata(c, 'HyperlinkClicked'))
        return
    if a == 'changing':
        v = _from_page(c, ev.get('value'))
        queue(c, 'ValueChangingFcn', evdata(c, 'ValueChanging', Value=v))
        return
    if a == 'value':
        old = p.get('Value')
        try:
            new = c._check_value(_from_page(c, ev.get('value')))
        except MError:
            # a number outside the Limits typed: the field keeps its value
            c.touch()
            return
        if c.KIND in ('radiobutton', 'togglebutton') and c.parent is not None and c.parent.TYPE == 'uibuttongroup':
            grp = c.parent
            was = grp.selection()
            grp.select(c)
            if was is not c:
                queue(grp, 'SelectionChangedFcn', evdata(grp, 'SelectionChanged', OldValue=was if was is not None else EMPTY(), NewValue=c))
            return
        p['Value'] = new
        c.touch()
        queue(c, 'ValueChangedFcn', evdata(c, 'ValueChanged', Value=new, PreviousValue=old if old is not None else EMPTY()))
