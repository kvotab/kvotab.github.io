"""The figure's property editor: what the page shows of a graphics object
(the figure's objects as a tree, the object's properties in groups, each
with the kind of field that edits it) and a change made there, which goes
through setprop as set(h, name, value) does.

A value typed in the editor is read as a literal (numbers, a matrix in
brackets, text, a color), never run as code; only a callback that starts
with @ is made into a function handle, as str2func makes one.
"""
import json
import math
import re

import numpy as np

from .values import MError, Char, Cell, Str, FH, EMPTY, py_str, numel
from . import graphics_base as G

_LINESTYLES = ['-', '--', ':', '-.', 'none']
_FIG_UNITS = ['pixels', 'normalized', 'inches', 'centimeters', 'points', 'characters']
_LEGEND_PLACES = ['north', 'south', 'east', 'west', 'northeast', 'northwest', 'southeast', 'southwest', 'northoutside',
                  'southoutside', 'eastoutside', 'westoutside', 'northeastoutside', 'northwestoutside', 'southeastoutside',
                  'southwestoutside', 'best', 'bestoutside', 'none']
_CBAR_PLACES = ['north', 'south', 'east', 'west', 'northoutside', 'southoutside', 'eastoutside', 'westoutside']

# the values a property takes, by name (or by object type and name)
ENUMS = {
    'LineStyle': _LINESTYLES, 'GridLineStyle': _LINESTYLES, 'MinorGridLineStyle': _LINESTYLES,
    'Marker': ['none', 'o', '+', '*', '.', 'x', 's', 'd', '^', 'v', '>', '<', 'p', 'h', '_', '|'],
    'FontWeight': ['normal', 'bold'], 'TitleFontWeight': ['normal', 'bold'], 'FontAngle': ['normal', 'italic'],
    'Interpreter': ['tex', 'latex', 'none'], 'TickLabelInterpreter': ['tex', 'latex', 'none'],
    'HorizontalAlignment': ['left', 'center', 'right'], 'VerticalAlignment': ['middle', 'top', 'bottom', 'baseline', 'cap'],
    'XScale': ['linear', 'log'], 'YScale': ['linear', 'log'], 'ZScale': ['linear', 'log'],
    'XDir': ['normal', 'reverse'], 'YDir': ['normal', 'reverse'], 'ZDir': ['normal', 'reverse'], 'Direction': ['normal', 'reverse'],
    'TickDir': ['in', 'out', 'both'], 'TickDirection': ['in', 'out', 'both'],
    'XAxisLocation': ['bottom', 'top', 'origin'], 'YAxisLocation': ['left', 'right', 'origin'], 'Layer': ['bottom', 'top'],
    'Projection': ['orthographic', 'perspective'], 'CDataMapping': ['direct', 'scaled'],
    'FaceLighting': ['none', 'flat', 'gouraud'], 'EdgeLighting': ['none', 'flat', 'gouraud'],
    'BackFaceLighting': ['unlit', 'lit', 'reverselit'], 'MeshStyle': ['both', 'row', 'column'],
    'Orientation': ['vertical', 'horizontal'], 'HandleVisibility': ['on', 'callback', 'off'], 'BusyAction': ['queue', 'cancel'],
    'PickableParts': ['visible', 'all', 'none'], 'WindowStyle': ['normal', 'modal', 'docked'],
    'WindowState': ['normal', 'minimized', 'maximized', 'fullscreen'], 'MenuBar': ['figure', 'none'],
    'ToolBar': ['auto', 'figure', 'none'], 'SortMethod': ['depth', 'childorder'],
    'ActivePositionProperty': ['outerposition', 'position'], 'Enable': ['on', 'off', 'inactive'],
    'FontUnits': ['points', 'pixels', 'inches', 'centimeters', 'normalized'], 'Units': _FIG_UNITS,
    'HeadStyle': list(G.HEAD_STYLES), 'Head1Style': list(G.HEAD_STYLES), 'Head2Style': list(G.HEAD_STYLES),
    'Pointer': ['arrow', 'crosshair', 'watch', 'hand', 'ibeam', 'fleur', 'circle', 'cross', 'topl', 'topr', 'botl', 'botr',
                'left', 'right', 'top', 'bottom'],
    'TitlePosition': ['lefttop', 'centertop', 'righttop', 'leftbottom', 'centerbottom', 'rightbottom'],
    'BorderType': ['none', 'etchedin', 'etchedout', 'beveledin', 'beveledout', 'line'],
    'NextPlot': ['replace', 'add', 'replacechildren', 'replaceall'], 'InvertHardcopy': ['on', 'off'],
    'Renderer': ['opengl', 'painters'], 'PaperOrientation': ['portrait', 'landscape'],
    ('figure', 'NextPlot'): ['add', 'new', 'replace', 'replacechildren'],
    ('legend', 'Location'): _LEGEND_PLACES, ('colorbar', 'Location'): _CBAR_PLACES,
    ('text', 'Units'): ['data', 'normalized', 'pixels', 'points', 'inches', 'centimeters', 'characters'],
    ('light', 'Style'): ['infinite', 'local'],
    ('uicontrol', 'Style'): ['pushbutton', 'togglebutton', 'radiobutton', 'checkbox', 'edit', 'text', 'slider', 'listbox',
                             'popupmenu', 'frame'],
    ('histogram', 'Normalization'): ['count', 'probability', 'countdensity', 'pdf', 'cumcount', 'cdf'],
}

# the properties shown first, by object type
COMMON = {
    'figure': ['Name', 'Color', 'Colormap', 'NumberTitle', 'Position'],
    'axes': ['Title', 'XLabel', 'YLabel', 'ZLabel', 'XLim', 'YLim', 'XScale', 'YScale', 'XGrid', 'YGrid', 'Box', 'FontSize'],
    'line': ['Color', 'LineStyle', 'LineWidth', 'Marker', 'MarkerSize', 'MarkerFaceColor', 'DisplayName'],
    'text': ['String', 'FontSize', 'FontWeight', 'Color', 'Interpreter', 'Rotation'],
    'legend': ['String', 'Location', 'Orientation', 'NumColumns', 'FontSize', 'Box'],
    'colorbar': ['Label', 'Location', 'Limits', 'FontSize', 'Direction'],
    'surface': ['FaceColor', 'EdgeColor', 'FaceAlpha', 'LineStyle', 'FaceLighting', 'DisplayName'],
    'patch': ['FaceColor', 'EdgeColor', 'FaceAlpha', 'LineStyle', 'LineWidth', 'DisplayName'],
    'image': ['CDataMapping', 'AlphaData', 'XData', 'YData'],
    'series': ['FaceColor', 'EdgeColor', 'Color', 'LineStyle', 'LineWidth', 'Marker', 'MarkerSize', 'MarkerFaceColor',
               'BarWidth', 'DisplayName'],
    'shape': ['String', 'Color', 'LineStyle', 'LineWidth', 'HeadStyle', 'FaceColor', 'FontSize', 'Position'],
    'ui': ['String', 'Title', 'Label', 'Text', 'Style', 'Value', 'Enable', 'Position', 'Callback'],
}

# Title and labels: shown with their axes (or colorbar) as text fields, kept by their Text objects
_ROLE_TEXTS = {'Title': 'title', 'Subtitle': 'subtitle', 'XLabel': 'xlabel', 'YLabel': 'ylabel', 'ZLabel': 'zlabel'}

_READONLY = {'Type', 'BeingDeleted', 'CurrentPoint', 'CurrentCharacter', 'CurrentKey', 'CurrentModifier', 'CurrentObject',
             'SelectionType', 'Number', 'Extent', 'Children', 'Parent', 'UserData', 'FileName', 'Layout', 'XAxis', 'YAxis',
             'ZAxis'}
_HIST_READONLY = {'Values', 'BinEdges', 'NumBins', 'BinWidth', 'Normalization', 'Data'}
_BIG = 400          # arrays with more elements are shown, not edited


def _kind_of(o):
    """The COMMON key of an object."""
    t = o.TYPE
    if isinstance(o, G.Series):
        return 'series'
    if isinstance(o, G.Shape):
        return 'shape'
    if t in COMMON:
        return t
    return 'ui'


def _group(o, k):
    """The group a property is shown in."""
    if k in _ROLE_TEXTS or k == 'Label' and o.TYPE == 'colorbar':
        return 'Labels'
    if k.endswith('Fcn') or k.endswith('Callback') or k in ('Interruptible', 'BusyAction'):
        return 'Callbacks'
    if k in ('Position', 'OuterPosition', 'InnerPosition', 'Units', 'ActivePositionProperty', 'WindowStyle', 'WindowState',
             'Resize', 'X', 'Y'):
        return 'Position'
    if k in ('Visible', 'HitTest', 'PickableParts', 'Selected', 'SelectionHighlight', 'HandleVisibility', 'Tag', 'UserData',
             'Clipping', 'UIContextMenu', 'Parent', 'Children', 'Type', 'BeingDeleted', 'Enable', 'TooltipString', 'Tooltip'):
        return 'Identity and interaction'
    if o.TYPE == 'axes':
        if re.match(r'^[XYZC]Lim', k) or k.startswith('BubbleLim') or k.startswith('ALim'):
            return 'Limits'
        if 'Tick' in k:
            return 'Ticks'
        if 'Grid' in k:
            return 'Grid'
        if re.match(r'^[XYZ](Scale|Dir|AxisLocation)$', k):
            return 'Scale and direction'
        if k.startswith('Camera') or 'AspectRatio' in k or k in ('View', 'Projection'):
            return 'View'
    if k.startswith('Font') or k in ('Interpreter', 'TitleFontSizeMultiplier', 'LabelFontSizeMultiplier', 'TitleFontWeight'):
        return 'Font'
    if k.startswith('Marker'):
        return 'Markers'
    if k in ('String', 'HorizontalAlignment', 'VerticalAlignment', 'Rotation', 'Margin') or k.startswith('Text'):
        return 'Text'
    if k.endswith('Data') or k in ('Vertices', 'Faces', 'BinEdges', 'Values', 'NumBins', 'BinWidth', 'Normalization',
                                   'LevelList', 'LevelListMode', 'DataMapping', 'CDataMapping', 'AlphaDataMapping'):
        return 'Data'
    if 'Color' in k or 'Alpha' in k or 'Line' in k or k.endswith('Style') or 'Lighting' in k or k in ('Colormap', 'Box'):
        return 'Colors and lines'
    return 'Other'


_GROUPS = ['Labels', 'Limits', 'Scale and direction', 'Ticks', 'Grid', 'Colors and lines', 'Markers', 'Text', 'Font', 'Data',
           'View', 'Position', 'Identity and interaction', 'Callbacks', 'Other']


def _fmt(x):
    """A number as typed back: the shortest text that reads as the same double."""
    x = float(x)
    if math.isnan(x):
        return 'NaN'
    if math.isinf(x):
        return 'Inf' if x > 0 else '-Inf'
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return repr(x)


def _array_text(a):
    a = np.asarray(a)
    if a.dtype.kind == 'b':
        a = a.astype(float)
    if a.size == 1:
        return _fmt(a.reshape(-1)[0])
    if a.ndim == 1:
        a = a.reshape(1, -1)
    if a.size == 0:
        return '[]'
    return '[' + '; '.join(' '.join(_fmt(x) for x in row) for row in a.reshape(a.shape[0], -1)) + ']'


def _summary(v):
    from .display import summary
    try:
        return summary(v)
    except Exception:
        return type(v).__name__


def label(o):
    """How an object is named in the tree and in links."""
    if o is None:
        return ''
    t = o.TYPE
    p = o.props
    if t == 'figure':
        n = p.get('Number', 0)
        name = p.get('Name', '')
        return (f'Figure {int(n)}' if n >= 0 else 'Dialog') + (f': {name}' if name else '')
    name = o.cls.split('.')[-1] if isinstance(o, G.GObj) else type(o).__name__
    if name == 'ColorBar':
        name = 'Colorbar'
    if t == 'axes' and getattr(o, 'yy_owner', None) is not None:
        name = 'Axes (right y)'
    detail = ''
    for k in ('DisplayName', 'String', 'Title', 'Label', 'Text'):
        v = p.get(k)
        if isinstance(v, list):
            v = v[0] if v else ''
        if type(v) in (Char, Str):
            v = py_str(v) if numel(v) else ''
        if isinstance(v, str) and v:
            detail = v
            break
    if not detail and t == 'axes':
        s = o.title.props.get('String', '')
        detail = s[0] if isinstance(s, list) and s else s if isinstance(s, str) else ''
    if not detail and isinstance(p.get('Tag'), str):
        detail = p['Tag']
    detail = detail.replace('\n', ' ')
    if len(detail) > 32:
        detail = detail[:31] + '…'
    return f"{name} '{detail}'" if detail else name


def _tree(fig):
    """The figure's objects, depth first: axes with their title and labels,
    plotted objects, legend and colorbar; annotations; a program's controls."""
    rows = []

    def add(o, depth, name=None):
        rows.append({'id': o.id, 'label': name or label(o), 'depth': depth, 'type': o.TYPE})

    def texts(owner, depth, pairs):
        for role, t in pairs:
            if t is None or not t.valid:
                continue
            s = t.props.get('String', '')
            s = ' '.join(s) if isinstance(s, list) else s
            if role in ('Subtitle', 'Z label') and not s and not (role == 'Z label' and owner.is3d()):
                continue
            short = s if len(s) <= 28 else s[:27] + '…'
            add(t, depth, f"{role} '{short}'" if short else role)

    def axes(ax, depth):
        add(ax, depth)
        texts(ax, depth + 1, [('Title', ax.title), ('Subtitle', ax.subtitle), ('X label', ax.xlabel), ('Y label', ax.ylabel),
                              ('Z label', ax.zlabel)])
        for c in reversed(ax.children):
            if c.valid and not getattr(c, 'hidden', False):
                walk(c, depth + 1)
        right = (ax.yy or {}).get('right')
        if right is not None and right.valid:
            add(right, depth + 1)
            texts(right, depth + 2, [('Y label', right.ylabel)])
            for c in reversed(right.children):
                if c.valid and not getattr(c, 'hidden', False):
                    walk(c, depth + 2)
        if ax.legend is not None and ax.legend.valid:
            add(ax.legend, depth + 1)
        cb = ax.colorbar
        if cb is not None and cb.valid:
            add(cb, depth + 1)
            s = cb.label.props.get('String', '')
            add(cb.label, depth + 2, f"Label '{s}'" if isinstance(s, str) and s else 'Label')

    def walk(o, depth):
        if o.TYPE == 'axes':
            if o.yy_owner is None:
                axes(o, depth)
            return
        if o.TYPE in ('legend', 'colorbar'):
            return
        add(o, depth)
        for c in reversed(o.children):
            if c.valid:
                walk(c, depth + 1)

    add(fig, 0)
    st = getattr(fig, 'sgtitle', None)
    if st is not None and st.valid:
        s = st.props.get('String', '')
        add(st, 1, f"Super title '{s}'" if isinstance(s, str) and s else 'Super title')
    for c in reversed(fig.children):
        if c.valid:
            walk(c, 1)
    return rows


def _options(o, k):
    return ENUMS.get((o.TYPE, k)) or ENUMS.get(k)


def _text_owner(o, k):
    """The Text object that keeps an axes' title or label (or a colorbar's label)."""
    if o.TYPE == 'axes' and k in _ROLE_TEXTS:
        return getattr(o, _ROLE_TEXTS[k])
    if o.TYPE == 'colorbar' and k == 'Label':
        return o.label
    return None


def _lines(v):
    if isinstance(v, list):
        return [str(s) for s in v]
    if isinstance(v, str):
        return v.split('\n') if v else ['']
    if type(v) is Char:
        return v.row_strs() if v.a.ndim == 2 and v.a.shape[0] > 1 else [v.str()]
    if type(v) is Str:
        return [s or '' for s in v.a.reshape(-1, order='F')]
    if type(v) is Cell:
        return [py_str(x) if type(x) in (Char, Str) else _summary(x) for x in v.a.reshape(-1, order='F')]
    if type(v) is np.ndarray and v.size == 0:
        return []
    return None


def describe(o, k):
    """One property for the page: its name, the field that edits it, and the value in that field's terms."""
    d = {'name': k}
    owner = _text_owner(o, k)
    if owner is not None:
        d.update(kind='lines', value=_lines(owner.props.get('String', '')), target=owner.id)
        return d
    raw = o.props.get(k)
    try:
        v = o.getprop(k)
    except MError:
        v = raw
    hist = isinstance(o, G.Series) and o.kind == 'histogram' and k in _HIST_READONLY
    if k in ('Parent', 'CurrentAxes', 'UIContextMenu', 'SelectedObject', 'SelectedTab', 'Legend') or isinstance(v, G.GObj):
        h = v if isinstance(v, G.GObj) else None
        d.update(kind='link', value=label(h) if h is not None else '(none)', link=h.id if h is not None and h.valid else None)
        return d
    if k in _READONLY or hist or isinstance(v, G.HArr):
        d.update(kind='readonly', value=_summary(v))
        return d
    if k in G._COLOR_PROPS or (k.endswith('Color') and isinstance(raw, tuple) and len(raw) == 3):
        keys = list(G._COLOR_PROPS.get(k, ()))
        if isinstance(raw, tuple):
            d.update(kind='color', value=[float(x) for x in raw], options=keys)
        else:
            s = raw if isinstance(raw, str) else 'none' if raw is None else _summary(v)
            if s not in keys:
                keys.append(s)
            d.update(kind='color', value=s, options=keys)
        return d
    if k == 'Enable':
        s = 'inactive' if raw == 'inactive' else 'on' if raw is True or raw == 'on' else 'off'
        d.update(kind='enum', value=s, options=ENUMS['Enable'])
        return d
    if k in G._ONOFF or isinstance(raw, bool):
        d.update(kind='onoff', value=bool(raw))
        return d
    if k.endswith('Mode') and raw in ('auto', 'manual'):
        d.update(kind='enum', value=raw, options=['auto', 'manual'])
        return d
    opts = _options(o, k)
    if opts and isinstance(raw, str):
        opts = list(opts) if raw in opts else list(opts) + [raw]
        d.update(kind='enum', value=raw, options=opts)
        return d
    if k == 'Colormap':
        from .colormaps import NAMES, colormap_by_name
        a = np.asarray(v, float)
        rows = int(a.shape[0]) if a.ndim == 2 else 0
        # a named map is shown by its name
        name = next((n for n in NAMES if rows and a.shape == (rows, 3) and np.allclose(colormap_by_name(n, rows), a, atol=1e-9)), None)
        d.update(kind='colormap', value=_summary(v), options=list(NAMES), rows=rows, current=name)
        return d
    if isinstance(v, FH) or k.endswith('Fcn') or k.endswith('Callback'):
        if isinstance(v, FH):
            d.update(kind='callback', value=_summary(v))
        elif type(v) in (Char, Str) or isinstance(raw, str):
            d.update(kind='callback', value=py_str(v) if type(v) in (Char, Str) else raw)
        else:
            d.update(kind='readonly', value=_summary(v))
        return d
    if k == 'String' or k.endswith('TickLabel') or k in ('TickLabels', 'Labels', 'ColumnName', 'RowName'):
        ls = _lines(v)
        if ls is not None:
            d.update(kind='lines', value=ls)
            return d
    if type(v) is float or type(v) is bool or (type(v) is np.ndarray and v.dtype.kind in 'fiub' and v.ndim <= 2):
        a = np.asarray(v)
        if a.size <= _BIG and (a.dtype.kind != 'f' or a.dtype == np.float64) and not np.iscomplexobj(a):
            d.update(kind='number' if a.size == 1 else 'array', value=_array_text(a))
        else:
            d.update(kind='readonly', value=_summary(v))
        return d
    if type(v) is Char and (v.a.ndim == 2 and v.a.shape[0] <= 1):
        d.update(kind='text', value=v.str())
        return d
    if type(v) is Str and v.a.size == 1 and v.a.flat[0] is not None:
        d.update(kind='text', value=v.a.flat[0])
        return d
    if type(v) is Cell and all(type(x) in (Char, Str) for x in v.a.reshape(-1)) and v.a.size <= _BIG:
        d.update(kind='lines', value=_lines(v))
        return d
    d.update(kind='readonly', value=_summary(v))
    return d


def _names(o):
    names = [n for n in o.propnames() if n not in ('Children',)]
    if o.TYPE == 'axes':
        names += ['Title', 'Subtitle', 'XLabel', 'YLabel', 'ZLabel', 'Legend']
    if o.TYPE == 'colorbar':
        names.append('Label')
    seen = set()
    out = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def inspect(o):
    """What the page shows of o: its name, the figure's tree, and its properties in groups."""
    fig = o.figure() if isinstance(o, G.GObj) else None
    names = _names(o)
    common = [n for n in COMMON.get(_kind_of(o), []) if n in names]
    groups = {}
    for n in names:
        if n in common:
            continue
        groups.setdefault(_group(o, n), []).append(n)
    out = [{'name': 'Common', 'props': [describe(o, n) for n in common]}] if common else []
    for g in _GROUPS:
        if g in groups:
            out.append({'name': g, 'props': [describe(o, n) for n in sorted(groups[g], key=str.lower)]})
    return {'ok': True, 'id': o.id, 'type': o.TYPE, 'label': label(o), 'figure': fig.id if fig is not None else None,
            'figureLabel': label(fig) if fig is not None else '', 'tree': _tree(fig) if fig is not None else [], 'groups': out}


# ---- values typed in the editor ------------------------------------------------------------------------

_NUM = {'pi': math.pi, '-pi': -math.pi, 'inf': math.inf, '+inf': math.inf, '-inf': -math.inf, 'nan': math.nan,
        'true': 1.0, 'false': 0.0, 'eps': 2.0 ** -52}


def _number(tok):
    low = tok.lower()
    if low in _NUM:
        return _NUM[low]
    if not re.fullmatch(r'[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?', tok):
        raise MError('MATLAB:graphics', f"'{tok}' is not a number.")
    return float(tok)


def parse_numbers(text):
    """'[1 2; 3 4]', '1, 2, 3' or '5' as numbers (a scalar, a row or a matrix); '' and '[]' as []."""
    s = text.strip()
    if s.startswith('[') and s.endswith(']'):
        s = s[1:-1].strip()
    if not s:
        return EMPTY()
    rows = [r for r in re.split(r'[;\n]', s)]
    if rows and not rows[-1].strip():
        rows.pop()
    grid = []
    for r in rows:
        toks = [t for t in re.split(r'[\s,]+', r.strip()) if t]
        grid.append([_number(t) for t in toks])
    if len({len(r) for r in grid}) > 1:
        raise MError('MATLAB:graphics', 'Each row needs the same number of values.')
    a = np.array(grid, float)
    if a.size == 1:
        return float(a[0, 0])
    return a


def _lines_value(lines):
    lines = [str(s) for s in lines]
    if len(lines) == 1:
        return Char.of(lines[0])
    return Cell.of_list([Char.of(s) for s in lines], (len(lines), 1))


def value_of(o, k, p):
    """A value from the editor (a JSON dict) as the language's value for setprop."""
    kind = p.get('kind')
    if kind == 'onoff':
        return Char.of('on' if p.get('value') else 'off')
    if kind == 'lines':
        v = p.get('value')
        return _lines_value(v if isinstance(v, list) else str(v or '').split('\n'))
    if kind == 'color':
        v = p.get('value')
        if isinstance(v, list):
            return np.array([[float(x) for x in v]])
        s = str(v or '').strip()
        if re.match(r'^\[?[\d.\s,eE+-]+\]?$', s):
            return parse_numbers(s)
        return Char.of(s)
    if kind == 'colormap':
        from .colormaps import NAMES, colormap_by_name
        name = str(p.get('value', ''))
        if name not in NAMES:
            raise MError('MATLAB:graphics', f"'{name}' is not a colormap.")
        return colormap_by_name(name, int(p.get('rows') or 256))
    if kind == 'callback':
        s = str(p.get('value', '')).strip()
        if s.startswith('@'):
            from .builtins.core import anon_from_text
            from . import runtime as R
            if s[1:].strip() and not s[1:].lstrip().startswith('('):
                name = s[1:].strip()
                if not re.fullmatch(r'[A-Za-z]\w*(\.[A-Za-z]\w*)*', name):
                    raise MError('MATLAB:graphics', f"'{s}' is not a function handle.")
                return R.NamedFH(name)
            return anon_from_text(s)
        return Char.of(s)
    if kind in ('number', 'array'):
        return parse_numbers(str(p.get('value', '')))
    if kind in ('enum', 'text'):
        return Char.of(str(p.get('value', '')))
    raise MError('MATLAB:graphics', f'{k} cannot be changed here.')


def change(o, k, p):
    """Set one property from the editor. A title or label is set on its Text object."""
    owner = _text_owner(o, k)
    if owner is not None:
        owner.setprop('String', value_of(o, k, p))
        return
    if describe(o, k)['kind'] in ('readonly', 'link'):
        raise MError('MATLAB:graphics', f'{k} cannot be changed here.')
    o.setprop(k, value_of(o, k, p))


def inspect_json(obj_id):
    o = G.STORE.objects.get(int(obj_id)) if obj_id is not None else None
    if o is None or not getattr(o, 'valid', False):
        return json.dumps({'ok': False, 'error': 'That object has been deleted.'})
    return json.dumps(inspect(o), allow_nan=False)


def change_json(obj_id, name, payload):
    o = G.STORE.objects.get(int(obj_id))
    if o is None or not o.valid:
        return json.dumps({'ok': False, 'error': 'That object has been deleted.'})
    error = None
    try:
        change(o, name, json.loads(payload))
    except MError as e:
        error = e.message
    except (ValueError, TypeError) as e:
        error = str(e)
    if not o.valid:
        return json.dumps({'ok': False, 'error': error or 'That object has been deleted.'})
    d = inspect(o)
    if error:
        d['error'] = error
        d['errorProp'] = name
    return json.dumps(d, allow_nan=False)
