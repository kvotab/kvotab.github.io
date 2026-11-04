"""Charts beyond the basic plots: constant lines and regions (xline, yline,
xregion, yregion), heatmap, boxchart, swarmchart, piechart and donutchart,
stackedplot, plotyy, polarhistogram, binscatter, parallelplot,
scatterhistogram and wordcloud.

Most are drawn from the ordinary graphics objects (lines, patches, texts,
images) in an axes, and given back as a chart object whose main properties
can be read and set (setting one draws the chart again). xline, yline,
xregion and yregion are lines and patches that the page stretches across the
axes whatever its limits are; they do not change the limits."""
import math

import numpy as np

from . import bi as _register
from ._util import err, nargchk, out, num, opt_str, is_str, darr, arr
from ..values import MError, Obj, Char, Cell, Struct, Str, FH, EMPTY, numel, py_str, text_list
from .. import runtime as R


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, ZeroDivisionError) as e:
                raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _g():
    from . import graphics as G
    return G


def _gb():
    from .. import graphics_base as GB
    return GB


def _pairs(rest, fn):
    if len(rest) % 2:
        raise err('MATLAB:InputParser:ParamMissingValue', f'{fn}: name-value arguments come in pairs.', fn)
    return [(py_str(rest[i]), rest[i + 1]) for i in range(0, len(rest), 2)]


def _color(v):
    return _gb().to_color(v, ('none', 'flat', 'interp', 'auto'))


def _texts(v):
    if isinstance(v, (Char, Str, Cell)):
        return text_list(v) if not isinstance(v, Char) or v.a.shape[0] > 1 else [v.str()]
    return [py_str(v)]


# ---- constant lines and regions ---------------------------------------------------------------------------------------------------

_CL = {}


def _constant_classes():
    if _CL:
        return _CL['line'], _CL['region']
    GB = _gb()

    class ConstantLine(GB.Line):
        CLASSNAME = 'matlab.graphics.chart.decoration.ConstantLine'
        NO_LIMITS = True
        DEFAULTS = dict(GB.Line.DEFAULTS, Label='', LabelVerticalAlignment='top', LabelHorizontalAlignment='right',
                        LabelOrientation='aligned', FontSize=9.0, FontWeight='normal', Alpha=0.7, InterceptAxis='x', Value=0.0)
        axis = 'x'

        def getprop(self, name):
            if name.lower() == 'type':
                return Char.of('constantline')
            if name.lower() == 'value':
                return float(np.asarray(self.props['XData' if self.axis == 'x' else 'YData'], float).reshape(-1)[0])
            if name.lower() == 'interceptaxis':
                return Char.of(self.axis)
            return super().getprop(name)

        def set_value(self, k, value):
            if k == 'Value':
                v = float(num(value))
                if self.axis == 'x':
                    self.props['XData'] = np.array([[v, v]])
                else:
                    self.props['YData'] = np.array([[v, v]])
                return
            if k == 'Label':
                self.props['Label'] = [py_str(x) for x in text_list(value)] if isinstance(value, Cell) else py_str(value)
                return
            if k in ('LabelVerticalAlignment', 'LabelHorizontalAlignment', 'LabelOrientation', 'FontWeight'):
                self.props[k] = py_str(value).lower()
                return
            super().set_value(k, value)

        def serial_extra(self):
            p = self.props
            lab = p['Label']
            return {'span': 'vertical' if self.axis == 'x' else 'horizontal', 'label': lab if lab else None,
                    'labelVertical': p['LabelVerticalAlignment'], 'labelHorizontal': p['LabelHorizontalAlignment'],
                    'labelOrientation': p['LabelOrientation'], 'fontSize': float(p['FontSize']), 'fontWeight': p['FontWeight']}

    class ConstantRegion(GB.Patch):
        CLASSNAME = 'matlab.graphics.chart.decoration.ConstantRegion'
        NO_LIMITS = True
        DEFAULTS = dict(GB.Patch.DEFAULTS, Value=lambda: np.zeros((1, 2)), InterceptAxis='x')
        axis = 'x'

        def getprop(self, name):
            if name.lower() == 'type':
                return Char.of('constantregion')
            if name.lower() == 'value':
                return np.asarray(self.props['XData' if self.axis == 'x' else 'YData'], float).reshape(1, -1).copy()
            if name.lower() == 'interceptaxis':
                return Char.of(self.axis)
            return super().getprop(name)

        def set_value(self, k, value):
            if k == 'Value':
                v = darr(value).reshape(-1)[:2].astype(float)
                self.props['XData' if self.axis == 'x' else 'YData'] = v.reshape(-1, 1)
                return
            super().set_value(k, value)

        def serial_extra(self):
            return {'span': 'vertical' if self.axis == 'x' else 'horizontal'}

    GB.register(ConstantLine, ConstantRegion)
    _CL['line'], _CL['region'] = ConstantLine, ConstantRegion
    return ConstantLine, ConstantRegion


def _constant_line(nargout, args, axis):
    G = _g()
    fn = 'xline' if axis == 'x' else 'yline'
    ax, rest = G.split_axes_arg(args)
    if not rest:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', fn)
    vals = darr(rest.pop(0), fn).reshape(-1)
    spec = None
    CLc, _ = _constant_classes()
    if rest and is_str(rest[0]) and G.parse_linespec(py_str(rest[0])) is not None and py_str(rest[0]).lower() not in CLc._lower:
        spec = G.parse_linespec(py_str(rest.pop(0)))
    labels = None
    if rest and (len(rest) % 2 == 1):
        labels = _texts(rest.pop(0))
    pairs = _pairs(rest, fn)
    ax = ax if ax is not None else G.gca_(G.gcf_())
    G.set_current_axes(ax)
    CL, _ = _constant_classes()
    hs = []
    for i, v in enumerate(vals):
        h = CL(ax)
        h.axis = axis
        h.props['Color'] = (0.15, 0.15, 0.15)
        if axis == 'x':
            h.props['XData'], h.props['YData'] = np.array([[v, v]]), np.array([[0.0, 1.0]])
        else:
            h.props['XData'], h.props['YData'] = np.array([[0.0, 1.0]]), np.array([[v, v]])
        if spec:
            col, ls, mk = spec
            if ls:
                h.props['LineStyle'] = ls
            if col is not None:
                h.props['Color'] = col
            if mk:
                h.props['Marker'] = mk
        if labels:
            h.props['Label'] = labels[i] if len(labels) == vals.size else labels[0] if len(labels) == 1 else labels
        G.apply_props(h, pairs)
        hs.append(h)
    ax.touch()
    return G.handles_out(hs) if nargout else None


@bi('xline')
def xline(nargout, *args):
    """xl = xline(x), xline(x, LineSpec, label, Name, Value), xline(ax, ...): vertical lines at x across the whole axes."""
    return _constant_line(nargout, args, 'x')


@bi('yline')
def yline(nargout, *args):
    """yl = yline(y, LineSpec, label, Name, Value): horizontal lines at y across the whole axes."""
    return _constant_line(nargout, args, 'y')


def _constant_region(nargout, args, axis):
    G = _g()
    fn = 'xregion' if axis == 'x' else 'yregion'
    ax, rest = G.split_axes_arg(args)
    nums = []
    while rest and not is_str(rest[0]):
        nums.append(darr(rest.pop(0), fn).reshape(-1))
    if len(nums) == 2:
        lo, hi = nums[0], nums[1]
    elif len(nums) == 1 and nums[0].size % 2 == 0:
        lo, hi = nums[0][0::2], nums[0][1::2]
    else:
        raise err('MATLAB:minrhs', f'{fn} takes the start and end of each region.', fn)
    pairs = _pairs(rest, fn)
    ax = ax if ax is not None else G.gca_(G.gcf_())
    G.set_current_axes(ax)
    _, CR = _constant_classes()
    hs = []
    for a, b in zip(lo, hi):
        h = CR(ax)
        h.axis = axis
        h.props['FaceColor'] = (0.0, 0.447, 0.741)
        h.props['FaceAlpha'] = 0.3
        h.props['EdgeColor'] = 'none'
        v = np.array([[float(a)], [float(b)]])
        if axis == 'x':
            h.props['XData'], h.props['YData'] = v, np.array([[0.0], [1.0]])
        else:
            h.props['XData'], h.props['YData'] = np.array([[0.0], [1.0]]), v
        G.apply_props(h, pairs)
        hs.append(h)
    ax.touch()
    return G.handles_out(hs) if nargout else None


@bi('xregion')
def xregion(nargout, *args):
    """xr = xregion(x1, x2), xregion([x1 x2 x3 x4 ...]), xregion(..., Name, Value): shaded bands from x1 to x2 across the whole axes."""
    return _constant_region(nargout, args, 'x')


@bi('yregion')
def yregion(nargout, *args):
    """yr = yregion(y1, y2, Name, Value): shaded bands from y1 to y2 across the whole axes."""
    return _constant_region(nargout, args, 'y')


# ---- charts as objects -------------------------------------------------------------------------------------------------------------

class Chart(Obj):
    """A chart drawn from graphics objects in an axes: its properties are read and set by name; setting one draws it again."""
    is_handle = True
    cls = 'matlab.graphics.chart.Chart'
    KEYS = ()
    SETTABLE = ()

    def __init__(self, ax, props):
        self.ax = ax
        self.p = dict(props)

    def _key(self, name):
        for k in self.p:
            if k.lower() == name.lower():
                return k
        return None

    def getprop(self, name):
        if name.lower() == 'parent':
            return self.ax.parent if self.ax is not None else EMPTY()
        k = self._key(name)
        if k is None:
            raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class '{self.cls.split('.')[-1]}'.")
        return self.p[k]

    def setprop(self, name, value):
        k = self._key(name)
        if k is None or (self.SETTABLE and k not in self.SETTABLE):
            raise MError('MATLAB:class:SetProhibited', f"The property '{name}' of {self.cls.split('.')[-1]} cannot be set here.")
        self.p[k] = value
        self.draw()

    def propnames(self):
        return list(self.p)

    def draw(self):
        pass

    def display_lines(self):
        from ..display import summary
        keys = [k for k in (self.KEYS or self.p) if k in self.p]
        w = max(len(k) for k in keys) if keys else 0
        return [f'  {self.cls.split(".")[-1]} with properties:', ''] + [f'    {k.rjust(w)}: {summary(self.p[k])}' for k in keys]

    def fresh_axes(self):
        """The chart's axes emptied for drawing it again."""
        ax = self.ax
        for c in list(ax.children):
            c.delete_handle()
        return ax


def _chart_axes(ax=None):
    G = _g()
    ax = G.newplot(ax)
    return ax


# ---- heatmap -----------------------------------------------------------------------------------------------------------------------------

class Heatmap(Chart):
    cls = 'matlab.graphics.chart.HeatmapChart'
    KEYS = ('XData', 'YData', 'ColorData', 'Title', 'XLabel', 'YLabel', 'ColorbarVisible', 'CellLabelFormat', 'ColorLimits', 'ColorMethod')

    def draw(self):
        G = _g()
        ax = self.fresh_axes()
        C = np.asarray(darr(self.p['ColorData']), float)
        m, n = C.shape
        scaling = py_str(self.p['ColorScaling']).lower()
        shown = C.copy()
        if scaling == 'scaledrows':
            lo, hi = np.nanmin(C, axis=1, keepdims=True), np.nanmax(C, axis=1, keepdims=True)
            shown = (C - lo) / np.where(hi > lo, hi - lo, 1)
        elif scaling == 'scaledcolumns':
            lo, hi = np.nanmin(C, axis=0, keepdims=True), np.nanmax(C, axis=0, keepdims=True)
            shown = (C - lo) / np.where(hi > lo, hi - lo, 1)
        elif scaling == 'log':
            with np.errstate(all='ignore'):
                shown = np.log(C)
        img = _gb().Image(ax)
        img.props['CData'] = shown
        img.props['XData'] = np.array([[1.0, float(n)]])
        img.props['YData'] = np.array([[1.0, float(m)]])
        img.props['CDataMapping'] = 'scaled'
        fin = shown[np.isfinite(shown)]
        lim = darr(self.p['ColorLimits']).reshape(-1) if numel(self.p['ColorLimits']) == 2 else (np.array([fin.min(), fin.max()]) if fin.size else np.array([0.0, 1.0]))
        if lim[1] <= lim[0]:
            lim = np.array([lim[0] - 0.5, lim[0] + 0.5])
        self.p['ColorLimits'] = lim.reshape(1, 2)
        ax.props['CLim'] = lim.reshape(1, 2)
        cm = np.asarray(darr(self.p['Colormap']), float)
        ax.props['Colormap'] = cm
        fig = ax.figure()
        fig.props['Colormap'] = cm
        fmt = py_str(self.p['CellLabelFormat'])
        if py_str(self.p['CellLabelColor']).lower() != 'none' if is_str(self.p['CellLabelColor']) else True:
            for i in range(m):
                for j in range(n):
                    v = C[i, j]
                    t = _gb().Text(ax)
                    t.props['String'] = 'NaN' if not np.isfinite(v) else (fmt % v if '%' in fmt else f'{v:.4g}')
                    t.props['Position'] = np.array([[j + 1.0, i + 1.0, 0.0]])
                    t.props['HorizontalAlignment'] = 'center'
                    t.props['FontSize'] = float(self.p['FontSize']) * 0.9
                    s = shown[i, j]
                    if np.isfinite(s):
                        k = int(np.clip(round((s - lim[0]) / (lim[1] - lim[0]) * (cm.shape[0] - 1)), 0, cm.shape[0] - 1))
                        lum = float(cm[k] @ np.array([0.299, 0.587, 0.114]))
                    else:
                        lum = 0.15
                    t.props['Color'] = (0.0, 0.0, 0.0) if lum > 0.5 else (1.0, 1.0, 1.0)
                    if is_str(self.p['CellLabelColor']) and py_str(self.p['CellLabelColor']).lower() != 'auto':
                        t.props['Color'] = _color(self.p['CellLabelColor'])
        if np.any(~np.isfinite(C)):
            # missing cells drawn over the image in MissingDataColor
            P = _gb().Patch(ax)
            ii, jj = np.nonzero(~np.isfinite(C))
            xs = np.vstack([jj + 0.5, jj + 1.5, jj + 1.5, jj + 0.5])
            ys = np.vstack([ii + 0.5, ii + 0.5, ii + 1.5, ii + 1.5])
            P.props['XData'], P.props['YData'] = xs, ys
            P.props['FaceColor'] = _color(self.p['MissingDataColor'])
            P.props['EdgeColor'] = 'none'
        xl, yl = _texts(self.p['XDisplayLabels']), _texts(self.p['YDisplayLabels'])
        ax.props['XLim'] = np.array([[0.5, n + 0.5]])
        ax.props['YLim'] = np.array([[0.5, m + 0.5]])
        ax.props['XLimMode'] = ax.props['YLimMode'] = 'manual'
        ax.props['YDir'] = 'reverse'
        ax.props['Box'] = True
        ax.props['TickLength'] = np.array([[0.0, 0.0]])
        R._builtin('xticks', ax, np.arange(1, n + 1, dtype=float).reshape(1, -1))
        R._builtin('yticks', ax, np.arange(1, m + 1, dtype=float).reshape(1, -1))
        R._builtin('xticklabels', ax, Cell.of_list([Char.of(s) for s in xl]))
        R._builtin('yticklabels', ax, Cell.of_list([Char.of(s) for s in yl]))
        if n > 6 and max((len(s) for s in xl), default=0) > 3:
            ax.props['XTickLabelRotation'] = 90.0
        R._builtin('title', ax, Char.of(py_str(self.p['Title'])) if is_str(self.p['Title']) else self.p['Title'])
        R._builtin('xlabel', ax, Char.of(py_str(self.p['XLabel'])) if is_str(self.p['XLabel']) else self.p['XLabel'])
        R._builtin('ylabel', ax, Char.of(py_str(self.p['YLabel'])) if is_str(self.p['YLabel']) else self.p['YLabel'])
        if bool(num(self.p['ColorbarVisible'])):
            R._builtin('colorbar', ax)
        ax.touch()


def _labels_of(v, n):
    if v is None:
        return [str(k + 1) for k in range(n)]
    if isinstance(v, (Cell, Str)) or (isinstance(v, Char) and v.a.shape[0] > 1):
        return text_list(v)
    if isinstance(v, Char):
        return [v.str()]
    a = darr(v).reshape(-1)
    return [f'{x:g}' for x in a]


def _group_values(v, n):
    """Each row's group as text, and the groups in order (categories in theirs, numbers and text sorted)."""
    from .categoricals import Categorical
    if isinstance(v, Categorical):
        names = list(np.asarray(v.names(), object).reshape(-1))
        return names, [c for c in v.cats if c in set(names)]
    if isinstance(v, (Cell, Str, Char)):
        t = text_list(v) if not isinstance(v, Char) else v.row_strs()
        return t, sorted(set(t))
    a = darr(v).reshape(-1)
    t = [f'{x:g}' for x in a]
    order = [f'{x:g}' for x in sorted(set(a[np.isfinite(a)].tolist()))]
    return t, order


@bi('heatmap')
def heatmap(nargout, *args):
    """h = heatmap(cdata), heatmap(xvalues, yvalues, cdata), heatmap(tbl, xvar, yvar, 'ColorVariable', cvar, 'ColorMethod', m): values as coloured cells with their numbers."""
    G = _g()
    from .tables import Table
    a = list(args)
    parent = None
    if a and G.is_axes(a[0]):
        parent = a.pop(0)
    opts = {}
    if a and isinstance(a[0], Table):
        T = a.pop(0)
        xv, yv = py_str(a.pop(0)), py_str(a.pop(0))
        o = dict((k.lower(), v) for k, v in _pairs(a, 'heatmap'))
        cvar = py_str(o.pop('colorvariable')) if 'colorvariable' in o else None
        method = py_str(o.pop('colormethod')).lower() if 'colormethod' in o else ('mean' if cvar else 'count')
        xs, xorder = _group_values(T.vars[T.names.index(xv)], T.n)
        ys, yorder = _group_values(T.vars[T.names.index(yv)], T.n)
        vals = darr(T.vars[T.names.index(cvar)]).reshape(-1) if cvar else np.ones(T.n)
        C = np.full((len(yorder), len(xorder)), np.nan)
        fns = {'count': len, 'mean': np.mean, 'sum': np.sum, 'median': np.median, 'max': np.max, 'min': np.min, 'none': (lambda v: v[0])}
        if method not in fns:
            raise err('MATLAB:heatmap:ColorMethod', "ColorMethod is 'count', 'mean', 'sum', 'median', 'max', 'min' or 'none'.", 'heatmap')
        xi = {k: j for j, k in enumerate(xorder)}
        yi = {k: i for i, k in enumerate(yorder)}
        cells = {}
        for r in range(T.n):
            if xs[r] in xi and ys[r] in yi and np.isfinite(vals[r]):
                cells.setdefault((yi[ys[r]], xi[xs[r]]), []).append(vals[r])
        for (i, j), v in cells.items():
            C[i, j] = fns[method](np.array(v))
        if method == 'count':
            C = np.nan_to_num(C, nan=0.0)
        xl, yl = xorder, yorder
        opts = {'XLabel': Char.of(xv), 'YLabel': Char.of(yv), 'ColorMethod': Char.of(method),
                'Title': Char.of(f'Count of {yv} vs. {xv}' if method == 'count' else f'{method.capitalize()} of {cvar}')}
        rest = [x for k, v in o.items() for x in (Char.of(k), v)]
    else:
        nums = []
        while a and not is_str(a[0]):
            nums.append(a.pop(0))
        if len(nums) == 1:
            C = np.asarray(darr(nums[0], 'heatmap'), float)
            xl, yl = _labels_of(None, C.shape[1]), _labels_of(None, C.shape[0])
        elif len(nums) == 3:
            C = np.asarray(darr(nums[2], 'heatmap'), float)
            xl, yl = _labels_of(nums[0], C.shape[1]), _labels_of(nums[1], C.shape[0])
        else:
            raise err('MATLAB:heatmap:inputs', 'heatmap(cdata), heatmap(xvalues, yvalues, cdata) or heatmap(tbl, xvar, yvar).', 'heatmap')
        rest = a
    if C.ndim != 2:
        raise err('MATLAB:heatmap:cdata', 'The color data is a matrix.', 'heatmap')
    from ..colormaps import colormap_by_name
    cm = np.asarray(colormap_by_name('parula', 256), float)
    props = {'XData': Cell.of_list([Char.of(s) for s in xl], (len(xl), 1)), 'YData': Cell.of_list([Char.of(s) for s in yl], (len(yl), 1)),
             'ColorData': C, 'XDisplayLabels': Cell.of_list([Char.of(s) for s in xl], (len(xl), 1)),
             'YDisplayLabels': Cell.of_list([Char.of(s) for s in yl], (len(yl), 1)), 'Title': Char.of(''), 'XLabel': Char.of(''), 'YLabel': Char.of(''),
             'ColorbarVisible': True, 'CellLabelFormat': Char.of('%0.4g'), 'CellLabelColor': Char.of('auto'), 'ColorLimits': EMPTY(),
             'Colormap': cm, 'ColorScaling': Char.of('none'), 'MissingDataColor': np.array([[0.15, 0.15, 0.15]]), 'FontSize': 10.0,
             'ColorMethod': Char.of('none'), 'GridVisible': True}
    props.update(opts)
    h = Heatmap(_chart_axes(parent), props)
    for k, v in _pairs(rest, 'heatmap'):
        kk = h._key(k)
        if kk is None:
            raise err('MATLAB:heatmap:property', f"'{k}' is not a property of heatmap.", 'heatmap')
        h.p[kk] = v
    h.draw()
    return h if nargout else None


# ---- boxchart and swarmchart -----------------------------------------------------------------------------------------------------------

def _box_stats(y):
    y = y[np.isfinite(y)]
    if y.size == 0:
        return None
    q1, med, q3 = (float(R._builtin('quantile', y.reshape(-1, 1), p)) for p in (0.25, 0.5, 0.75))
    iqr = q3 - q1
    lo_f, hi_f = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    inside = y[(y >= lo_f) & (y <= hi_f)]
    wl, wh = (float(inside.min()), float(inside.max())) if inside.size else (q1, q3)
    return {'q1': q1, 'med': med, 'q3': q3, 'wl': wl, 'wh': wh, 'out': y[(y < lo_f) | (y > hi_f)], 'n': y.size}


class BoxChart(Chart):
    cls = 'matlab.graphics.chart.primitive.BoxChart'
    KEYS = ('BoxFaceColor', 'BoxWidth', 'Orientation', 'Notch', 'MarkerStyle', 'XData', 'YData', 'DisplayName')

    def draw(self):
        GB = _gb()
        ax = self.ax
        for h in getattr(self, 'parts', []):
            if h.valid:
                h.delete_handle()
        self.parts = []
        x = darr(self.p['XData']).reshape(-1)
        y = darr(self.p['YData']).reshape(-1)
        horiz = py_str(self.p['Orientation']).lower() == 'horizontal'
        col = _color(self.p['BoxFaceColor'])
        w = float(num(self.p['BoxWidth']))
        notch = py_str(self.p['Notch']).lower() == 'on'
        mk = py_str(self.p['MarkerStyle'])
        off = float(self.p.get('_offset', 0.0))

        def put(xs, ys):
            return (ys, xs) if horiz else (xs, ys)
        for pos in np.unique(x[np.isfinite(x)]):
            s = _box_stats(y[x == pos])
            if s is None:
                continue
            c = pos + off
            if notch:
                nh = 1.57 * (s['q3'] - s['q1']) / math.sqrt(s['n'])
                bx = [c - w / 2, c + w / 2, c + w / 2, c + w / 4, c + w / 2, c + w / 2, c - w / 2, c - w / 2, c - w / 4, c - w / 2]
                by = [s['q1'], s['q1'], s['med'] - nh, s['med'], s['med'] + nh, s['q3'], s['q3'], s['med'] + nh, s['med'], s['med'] - nh]
                mx = [c - w / 4, c + w / 4]
            else:
                bx = [c - w / 2, c + w / 2, c + w / 2, c - w / 2]
                by = [s['q1'], s['q1'], s['q3'], s['q3']]
                mx = [c - w / 2, c + w / 2]
            P = GB.Patch(ax)
            px, py = put(np.array(bx, float), np.array(by, float))
            P.props['XData'], P.props['YData'] = px.reshape(-1, 1), py.reshape(-1, 1)
            P.props['FaceColor'] = col
            P.props['FaceAlpha'] = 0.2
            P.props['EdgeColor'] = col
            self.parts.append(P)
            segs_x = [mx, [c, c], [c, c], [c - w / 4, c + w / 4], [c - w / 4, c + w / 4]]
            segs_y = [[s['med'], s['med']], [s['q3'], s['wh']], [s['q1'], s['wl']], [s['wh'], s['wh']], [s['wl'], s['wl']]]
            for k, (sx, sy) in enumerate(zip(segs_x, segs_y)):
                L = GB.Line(ax)
                lx, ly = put(np.array(sx, float), np.array(sy, float))
                L.props['XData'], L.props['YData'] = lx.reshape(1, -1), ly.reshape(1, -1)
                L.props['Color'] = col if k == 0 else (0.15, 0.15, 0.15)
                L.props['LineWidth'] = 2.0 if k == 0 else 0.5
                self.parts.append(L)
            if s['out'].size and mk != 'none':
                L = GB.Line(ax)
                ox, oy = put(np.full(s['out'].size, c), s['out'])
                L.props['XData'], L.props['YData'] = ox.reshape(1, -1), oy.reshape(1, -1)
                L.props['LineStyle'] = 'none'
                L.props['Marker'] = mk
                L.props['Color'] = col
                self.parts.append(L)
        ax.touch()


@bi('boxchart')
def boxchart(nargout, *args):
    """b = boxchart(ydata), boxchart(xgroupdata, ydata), boxchart(..., 'GroupByColor', g, 'Notch', 'on', 'Orientation', 'horizontal', 'BoxFaceColor', c): box charts of the data's quartiles."""
    G = _g()
    a = list(args)
    ax, a = G.split_axes_arg(a)
    nums = []
    while a and not is_str(a[0]):
        nums.append(a.pop(0))
    o = dict((k.lower(), v) for k, v in _pairs(a, 'boxchart'))
    tick_labels = None
    if len(nums) == 1:
        Y = np.asarray(darr(nums[0], 'boxchart'), float)
        if Y.ndim == 1 or Y.shape[0] == 1:
            Y = Y.reshape(-1, 1)
        x = np.repeat(np.arange(1, Y.shape[1] + 1, dtype=float).reshape(1, -1), Y.shape[0], axis=0).reshape(-1, order='F')
        y = Y.reshape(-1, order='F')
    elif len(nums) == 2:
        from .categoricals import Categorical
        g = nums[0]
        y = darr(nums[1], 'boxchart').reshape(-1)
        if isinstance(g, (Categorical, Cell, Str)):
            names, order = _group_values(g, y.size)
            pos = {k: i + 1.0 for i, k in enumerate(order)}
            x = np.array([pos.get(t, np.nan) for t in names])
            tick_labels = order
        else:
            x = darr(g).reshape(-1).astype(float)
    else:
        raise err('MATLAB:boxchart:inputs', 'boxchart(ydata) or boxchart(xgroupdata, ydata).', 'boxchart')
    ax = G.newplot(ax)
    groups = None
    if 'groupbycolor' in o:
        gn, gorder = _group_values(o.pop('groupbycolor'), y.size)
        groups = (gn, gorder)
    hs = []
    base = {'BoxWidth': 0.5, 'Orientation': Char.of('vertical'), 'Notch': Char.of('off'), 'MarkerStyle': Char.of('o'), 'DisplayName': Char.of('')}
    for k in ('boxwidth', 'orientation', 'notch', 'markerstyle'):
        if k in o:
            base[{'boxwidth': 'BoxWidth', 'orientation': 'Orientation', 'notch': 'Notch', 'markerstyle': 'MarkerStyle'}[k]] = o.pop(k)
    sets = [(np.ones(y.size, bool), '')] if groups is None else [(np.array([t == k for t in groups[0]]), k) for k in groups[1]]
    ng = len(sets)
    for gi, (mask, name) in enumerate(sets):
        col = _color(o['boxfacecolor']) if 'boxfacecolor' in o else ax.next_color()
        props = dict(base, XData=x[mask].reshape(-1, 1), YData=y[mask].reshape(-1, 1), BoxFaceColor=np.array([col], float), DisplayName=Char.of(name))
        b = BoxChart(ax, props)
        if ng > 1:
            props['BoxWidth'] = float(num(props['BoxWidth'])) / ng * 1.6
            b.p['BoxWidth'] = props['BoxWidth']
            b.p['_offset'] = (gi - (ng - 1) / 2) * float(num(base['BoxWidth'])) / ng * 1.6
        b.draw()
        hs.append(b)
    horiz = py_str(base['Orientation']).lower() == 'horizontal'
    if tick_labels:
        R._builtin('yticks' if horiz else 'xticks', ax, np.arange(1, len(tick_labels) + 1, dtype=float).reshape(1, -1))
        R._builtin('yticklabels' if horiz else 'xticklabels', ax, Cell.of_list([Char.of(s) for s in tick_labels]))
    xs = x[np.isfinite(x)]
    if xs.size:
        lim = np.array([[xs.min() - 0.75, xs.max() + 0.75]])
        R._builtin('ylim' if horiz else 'xlim', ax, lim)
    if ng > 1:
        for b, (_, name) in zip(hs, sets):
            b.parts[0].props['DisplayName'] = name
    ax.touch()
    if nargout:
        return hs[0] if len(hs) == 1 else Cell.of_list(hs)
    return None


def _jitter(groups, y, width, method):
    """Offsets in [-width/2, width/2] for each point: uniform ('rand'), or scaled by the density of y in its group ('density')."""
    n = y.size
    u = darr(R._builtin('rand', float(n), 1.0)).reshape(-1) * 2 - 1
    off = np.zeros(n)
    for g in np.unique(groups):
        m = groups == g
        yy = y[m]
        if method == 'none':
            continue
        if method == 'density' and yy.size > 1 and np.std(yy) > 0:
            bw = 1.06 * np.std(yy) * yy.size ** (-0.2)
            d = np.exp(-0.5 * ((yy[:, None] - yy[None, :]) / bw) ** 2).sum(axis=1)
            scale = d / d.max()
        else:
            scale = np.ones(yy.size)
        off[m] = u[m] * scale * width / 2
    return off


def _swarm(nargout, args, three, fn):
    G = _g()
    a = list(args)
    ax, a = G.split_axes_arg(a)
    nums = []
    while a and not is_str(a[0]):
        nums.append(a.pop(0))
    k = 3 if three else 2
    if len(nums) < k:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', fn)
    rest = []
    jit = {'xjitter': 'density', 'yjitter': 'density' if three else 'none', 'xjitterwidth': 0.9, 'yjitterwidth': 0.9}
    i = 0
    while i < len(a):
        s_ = py_str(a[i]).lower() if is_str(a[i]) else ''
        if s_ in jit and i + 1 < len(a):
            jit[s_] = py_str(a[i + 1]).lower() if 'width' not in s_ else float(num(a[i + 1]))
            i += 2
            continue
        rest.append(a[i])
        i += 1
    xyz = [darr(v, fn).reshape(-1) for v in nums[:k]]
    n = max(v.size for v in xyz)
    xyz = [np.full(n, v[0]) if v.size == 1 else v for v in xyz]
    dens = xyz[-1]
    xyz[0] = xyz[0] + _jitter(np.round(xyz[0] * 1e9), dens, jit['xjitterwidth'], jit['xjitter'])
    if three:
        xyz[1] = xyz[1] + _jitter(np.round(xyz[1] * 1e9), dens, jit['yjitterwidth'], jit['yjitter'])
    call = [out(v.reshape(-1, 1)) for v in xyz] + list(nums[k:]) + rest
    h = R._builtin('scatter3' if three else 'scatter', *([ax] if ax is not None else []), *call)
    return h if nargout else None


@bi('swarmchart')
def swarmchart(nargout, *args):
    """s = swarmchart(x, y, sz, c, 'filled', 'XJitter', 'density', 'XJitterWidth', w): a scatter plot with the points of each x spread sideways by their density."""
    return _swarm(nargout, args, False, 'swarmchart')


@bi('swarmchart3')
def swarmchart3(nargout, *args):
    """s = swarmchart3(x, y, z, ...): a 3-D scatter plot with the points spread in x and y by the density of z."""
    return _swarm(nargout, args, True, 'swarmchart3')


# ---- pie and donut charts ---------------------------------------------------------------------------------------------------------------

class PieChart(Chart):
    cls = 'matlab.graphics.chart.PieChart'
    KEYS = ('Data', 'Names', 'LabelStyle', 'InnerRadius', 'CenterLabel', 'Title', 'FaceAlpha', 'StartAngle', 'Direction')

    def draw(self):
        GB = _gb()
        G = _g()
        ax = self.fresh_axes()
        d = darr(self.p['Data']).reshape(-1).astype(float)
        d = np.where(np.isfinite(d) & (d > 0), d, 0.0)
        names = _texts(self.p['Names']) if numel(self.p['Names']) else [f'{k + 1}' for k in range(d.size)]
        tot = d.sum() or 1.0
        inner = float(num(self.p['InnerRadius']))
        a0 = math.radians(float(num(self.p['StartAngle'])))
        sign = -1.0 if py_str(self.p['Direction']).lower() == 'clockwise' else 1.0
        style = py_str(self.p['LabelStyle']).lower()
        order = np.asarray(darr(self.p['ColorOrder']), float)
        ang = a0
        for k, v in enumerate(d):
            span = 2 * math.pi * v / tot
            if span <= 0:
                continue
            ts = np.linspace(ang, ang + sign * span, max(int(span / 0.03), 2))
            ox, oy = np.cos(ts), np.sin(ts)
            if inner > 0:
                xs = np.concatenate([ox, inner * ox[::-1]])
                ys = np.concatenate([oy, inner * oy[::-1]])
            else:
                xs, ys = np.concatenate([[0.0], ox]), np.concatenate([[0.0], oy])
            P = GB.Patch(ax)
            P.props['XData'], P.props['YData'] = xs.reshape(-1, 1), ys.reshape(-1, 1)
            P.props['FaceColor'] = tuple(order[k % order.shape[0]])
            P.props['FaceAlpha'] = float(num(self.p['FaceAlpha']))
            P.props['EdgeColor'] = (1.0, 1.0, 1.0)
            P.props['DisplayName'] = names[k] if k < len(names) else ''
            mid = ang + sign * span / 2
            pct = 100 * v / tot
            lab = {'percent': f'{pct:.0f}%', 'name': names[k], 'namepercent': f'{names[k]} ({pct:.0f}%)', 'data': f'{v:g}',
                   'namedata': f'{names[k]} ({v:g})', 'datapercent': f'{v:g} ({pct:.0f}%)', 'none': ''}.get(style, f'{pct:.0f}%')
            if lab:
                t = GB.Text(ax)
                rr = 1.15
                t.props['String'] = lab
                t.props['Position'] = np.array([[rr * math.cos(mid), rr * math.sin(mid), 0.0]])
                t.props['HorizontalAlignment'] = 'left' if math.cos(mid) > 0.1 else 'right' if math.cos(mid) < -0.1 else 'center'
            ang += sign * span
        if inner > 0 and numel(self.p['CenterLabel']):
            t = GB.Text(ax)
            t.props['String'] = py_str(self.p['CenterLabel'])
            t.props['Position'] = np.array([[0.0, 0.0, 0.0]])
            t.props['HorizontalAlignment'] = 'center'
            t.props['FontSize'] = 12.0
        ax.props['DataAspectRatio'] = np.array([[1.0, 1.0, 1.0]])
        ax.props['DataAspectRatioMode'] = 'manual'
        ax.props['XLim'] = np.array([[-1.6, 1.6]])
        ax.props['YLim'] = np.array([[-1.3, 1.3]])
        ax.props['XLimMode'] = ax.props['YLimMode'] = 'manual'
        ax.props['Visible'] = False
        if numel(self.p['Title']):
            R._builtin('title', ax, self.p['Title'])
            ax.title.props['Visible'] = True
        ax.touch()


def _pie_chart(nargout, args, fn, inner):
    G = _g()
    from .tables import Table
    a = list(args)
    ax, a = G.split_axes_arg(a)
    names = EMPTY()
    if a and isinstance(a[0], Table):
        T = a.pop(0)
        var = py_str(a.pop(0))
        if a and is_str(a[0]) and py_str(a[0]) in T.names and len(a) % 2 == 1:
            nv = py_str(a.pop(0))
            data = darr(T.vars[T.names.index(var)]).reshape(-1)
            names = Cell.of_list([Char.of(s) for s in _group_values(T.vars[T.names.index(nv)], T.n)[0]])
        else:
            from collections import Counter
            g, order = _group_values(T.vars[T.names.index(var)], T.n)
            cnt = Counter(g)
            data = np.array([float(cnt[k]) for k in order])
            names = Cell.of_list([Char.of(s) for s in order])
    else:
        from .categoricals import Categorical
        d0 = a.pop(0)
        if isinstance(d0, Categorical):
            from collections import Counter
            g, order = _group_values(d0, numel(d0))
            cnt = Counter(g)
            data = np.array([float(cnt[k]) for k in order])
            names = Cell.of_list([Char.of(s) for s in order])
        else:
            data = darr(d0, fn).reshape(-1)
            if a and not (is_str(a[0]) and len(a) % 2 == 0):
                names = a.pop(0)
    props = {'Data': data.reshape(-1, 1), 'Names': names, 'LabelStyle': Char.of('namepercent' if numel(names) else 'percent'),
             'InnerRadius': inner, 'CenterLabel': Char.of(''), 'Title': Char.of(''), 'FaceAlpha': 1.0, 'StartAngle': 90.0,
             'Direction': Char.of('clockwise'), 'ColorOrder': np.array(_gb().COLOR_ORDER, float)}
    ax = G.newplot(ax)
    h = PieChart(ax, props)
    for k, v in _pairs(a, fn):
        kk = h._key(k)
        if kk is None:
            raise err(f'MATLAB:{fn}:property', f"'{k}' is not a property of {fn}.", fn)
        h.p[kk] = v
    h.draw()
    return h if nargout else None


@bi('piechart')
def piechart(nargout, *args):
    """p = piechart(data), piechart(data, names), piechart(tbl, var), piechart(..., 'LabelStyle', s): a pie chart, its wedges labelled."""
    return _pie_chart(nargout, args, 'piechart', 0.0)


@bi('donutchart')
def donutchart(nargout, *args):
    """d = donutchart(data, names, 'InnerRadius', r, 'CenterLabel', s): a pie chart with a hole."""
    return _pie_chart(nargout, args, 'donutchart', 0.6)


# ---- stackedplot -------------------------------------------------------------------------------------------------------------------------

class StackedPlot(Chart):
    cls = 'matlab.graphics.chart.StackedLineChart'
    KEYS = ('Title', 'DisplayLabels', 'XLabel', 'XData')

    def __init__(self, axes, props):
        super().__init__(axes[0] if axes else None, props)
        self.axes = axes

    def draw(self):
        for ax, lab in zip(self.axes, _texts(self.p['DisplayLabels'])):
            R._builtin('ylabel', ax, Char.of(lab))
        if self.axes:
            R._builtin('title', self.axes[0], self.p['Title'])
            R._builtin('xlabel', self.axes[-1], self.p['XLabel'])
            for ax in self.axes:
                ax.touch()


@bi('stackedplot')
def stackedplot(nargout, *args):
    """s = stackedplot(tbl), stackedplot(tbl, vars), stackedplot(X, Y), stackedplot(Y), stackedplot(..., 'Title', t, 'DisplayLabels', labels, 'XVariable', v): each variable (or column) in an axes of its own, stacked, sharing x."""
    G = _g()
    from .tables import Table, TimeTable
    a = list(args)
    series, labels, xvals, xlabel = [], [], None, ''
    o = {}
    if a and isinstance(a[0], Table):
        T = a.pop(0)
        sel = None
        if a and not (is_str(a[0]) and py_str(a[0]).lower() in ('title', 'displaylabels', 'xvariable', 'xlabel', 'linewidth', 'color', 'marker', 'linestyle') and len(a) % 2 == 0):
            sel = T.var_index(a.pop(0))
        o = dict((k.lower(), v) for k, v in _pairs(a, 'stackedplot'))
        if isinstance(T, TimeTable):
            xvals = T.times
            xlabel = T.dims[0]
        elif 'xvariable' in o:
            xn = py_str(o.pop('xvariable'))
            xvals = T.vars[T.names.index(xn)]
            xlabel = xn
        idx = sel if sel is not None else [k for k in range(len(T.vars)) if not (xvals is not None and T.vars[k] is xvals)]
        for k in idx:
            v = T.vars[k]
            if type(v) is np.ndarray and v.dtype.kind in 'fiub':
                series.append(np.asarray(v, float))
                labels.append(T.names[k])
        if xvals is None:
            xvals = np.arange(1, T.n + 1, dtype=float)
    else:
        nums = []
        while a and not is_str(a[0]):
            nums.append(a.pop(0))
        o = dict((k.lower(), v) for k, v in _pairs(a, 'stackedplot'))
        Y = np.asarray(darr(nums[-1], 'stackedplot'), float)
        if Y.ndim == 1 or Y.shape[0] == 1:
            Y = Y.reshape(-1, 1)
        xvals = darr(nums[0]).reshape(-1) if len(nums) > 1 else np.arange(1, Y.shape[0] + 1, dtype=float)
        series = [Y[:, j] for j in range(Y.shape[1])]
        labels = [f'Column {j + 1}' for j in range(Y.shape[1])]
    if not series:
        raise err('MATLAB:stackedplot:noData', 'There is nothing numeric to plot.', 'stackedplot')
    f = G.gcf_()
    for c in list(f.children):
        if c.TYPE in ('axes', 'legend', 'colorbar'):
            c.delete_handle()
    n = len(series)
    left, right, bottom, top = 0.13, 0.95, 0.11, 0.92
    gap = 0.035
    h = (top - bottom - gap * (n - 1)) / n
    axes = []
    for k, y in enumerate(series):
        ax = R._builtin('axes', Char.of('Position'), np.array([[left, top - (k + 1) * h - k * gap, right - left, h]]))
        G.set_current_axes(ax)
        lw = o.get('linewidth', 0.5)
        R._builtin('plot', ax, xvals if not isinstance(xvals, np.ndarray) else xvals.reshape(-1, 1), y.reshape(-1, 1), Char.of('LineWidth'), lw)
        ax.props['XGrid'] = ax.props['YGrid'] = True
        if k < n - 1:
            R._builtin('xticklabels', ax, Cell.empty((1, 0)))
        axes.append(ax)
    R._builtin('linkaxes', _harr(axes), Char.of('x'))
    props = {'Title': o.get('title', Char.of('')), 'DisplayLabels': o.get('displaylabels', Cell.of_list([Char.of(s) for s in labels])),
             'XLabel': Char.of(xlabel), 'XData': xvals if not isinstance(xvals, np.ndarray) else xvals.reshape(-1, 1)}
    s = StackedPlot(axes, props)
    s.draw()
    return s if nargout else None


def _harr(hs):
    return _gb().HArr.of(hs, col=True)


# ---- plotyy -------------------------------------------------------------------------------------------------------------------------------

@bi('plotyy', nout=3)
def plotyy(nargout, *args):
    """[ax, h1, h2] = plotyy(x1, y1, x2, y2), plotyy(..., fun), plotyy(..., fun1, fun2): two plots with a y axis each, left and right."""
    G = _g()
    nargchk(args, 4, 6, 'plotyy')
    fun1 = args[4] if len(args) > 4 else Char.of('plot')
    fun2 = args[5] if len(args) > 5 else fun1

    def call(fun, x, y):
        if isinstance(fun, FH):
            return fun.scall(1, x, y)
        return R._builtin(py_str(fun), x, y)
    ax = G.newplot(None)
    R._builtin('yyaxis', ax, Char.of('left'))
    h1 = call(fun1, args[0], args[1])
    R._builtin('yyaxis', ax, Char.of('right'))
    h2 = call(fun2, args[2], args[3])
    right = ax.yy['right']
    R._builtin('yyaxis', ax, Char.of('left'))
    res = (_harr([ax, right]), h1, h2)
    return res[:nargout] if nargout > 1 else (res[0] if nargout else None)


# ---- polarhistogram --------------------------------------------------------------------------------------------------------------------

class PolarHistogram(Chart):
    cls = 'matlab.graphics.chart.primitive.Histogram'
    KEYS = ('Data', 'Values', 'NumBins', 'BinEdges', 'BinWidth', 'Normalization', 'FaceColor', 'FaceAlpha', 'DisplayStyle')

    def draw(self):
        GB = _gb()
        ax = self.ax
        for h in getattr(self, 'parts', []):
            if h.valid:
                h.delete_handle()
        self.parts = []
        th = np.mod(darr(self.p['Data']).reshape(-1), 2 * math.pi)
        th = th[np.isfinite(th)]
        edges = darr(self.p['BinEdges']).reshape(-1)
        counts = np.histogram(th, bins=edges)[0].astype(float)
        norm = py_str(self.p['Normalization']).lower()
        widths = np.diff(edges)
        vals = {'count': counts, 'probability': counts / max(th.size, 1), 'pdf': counts / max(th.size, 1) / widths,
                'countdensity': counts / widths, 'cumcount': np.cumsum(counts), 'cdf': np.cumsum(counts) / max(th.size, 1)}.get(norm, counts)
        self.p['Values'] = vals.reshape(1, -1)
        self.p['BinCounts'] = counts.reshape(1, -1)
        stairs = py_str(self.p['DisplayStyle']).lower() == 'stairs'
        fc = _color(self.p['FaceColor'])
        for k, v in enumerate(vals):
            ts = np.linspace(edges[k], edges[k + 1], max(int((edges[k + 1] - edges[k]) / 0.02), 2))
            xs = np.concatenate([[edges[k]], ts, [edges[k + 1]]])
            ys = np.concatenate([[0.0], np.full(ts.size, v), [0.0]])
            if stairs:
                L = GB.Line(ax)
                L.props['XData'], L.props['YData'] = xs.reshape(1, -1), ys.reshape(1, -1)
                L.props['Color'] = fc if isinstance(fc, tuple) else (0.0, 0.447, 0.741)
                self.parts.append(L)
            else:
                P = GB.Patch(ax)
                P.props['XData'], P.props['YData'] = xs.reshape(-1, 1), ys.reshape(-1, 1)
                P.props['FaceColor'] = fc
                P.props['FaceAlpha'] = float(num(self.p['FaceAlpha']))
                P.props['EdgeColor'] = (0.0, 0.0, 0.0)
                self.parts.append(P)
        ax.touch()


@bi('polarhistogram')
def polarhistogram(nargout, *args):
    """h = polarhistogram(theta), polarhistogram(theta, nbins), polarhistogram(theta, edges), polarhistogram(..., 'BinWidth', w, 'Normalization', n, 'DisplayStyle', 'stairs'): a histogram of angles (radians) in polar axes."""
    G = _g()
    a = list(args)
    ax, a = G.split_axes_arg(a)
    th = darr(a.pop(0), 'polarhistogram').reshape(-1)
    nb = None
    edges = None
    if a and not is_str(a[0]):
        v = darr(a.pop(0)).reshape(-1)
        if v.size == 1:
            nb = int(v[0])
        else:
            edges = v.astype(float)
    o = dict((k.lower(), v) for k, v in _pairs(a, 'polarhistogram'))
    if edges is None:
        if 'binwidth' in o:
            w = float(num(o.pop('binwidth')))
            edges = np.arange(0, 2 * math.pi, w)
            edges = np.append(edges, 2 * math.pi) if edges[-1] < 2 * math.pi - 1e-12 else edges
        else:
            if nb is None:
                t = np.mod(th[np.isfinite(th)], 2 * math.pi)
                nb = int(min(max(math.ceil(2 * t.size ** (1 / 3)), 1), 50)) if t.size else 10
            edges = np.linspace(0, 2 * math.pi, nb + 1)
    ax = G.newplot(ax, box=False)
    G._make_polar(ax)
    props = {'Data': th.reshape(-1, 1), 'BinEdges': edges.reshape(1, -1), 'NumBins': float(edges.size - 1), 'BinWidth': float(np.mean(np.diff(edges))),
             'Normalization': o.pop('normalization', Char.of('count')), 'FaceColor': o.pop('facecolor', Char.of('auto')),
             'FaceAlpha': o.pop('facealpha', 0.6), 'DisplayStyle': o.pop('displaystyle', Char.of('bar')), 'Values': EMPTY(), 'BinCounts': EMPTY()}
    if is_str(props['FaceColor']) and py_str(props['FaceColor']).lower() == 'auto':
        props['FaceColor'] = np.array([ax.next_color()], float)
    h = PolarHistogram(ax, props)
    h.draw()
    return h if nargout else None


# ---- binscatter --------------------------------------------------------------------------------------------------------------------------

class Binscatter(Chart):
    cls = 'matlab.graphics.chart.primitive.Binscatter'
    KEYS = ('XData', 'YData', 'NumBins', 'XLimits', 'YLimits', 'Values', 'ShowEmptyBins', 'FaceAlpha')

    def draw(self):
        GB = _gb()
        ax = self.ax
        for h in getattr(self, 'parts', []):
            if h.valid:
                h.delete_handle()
        x, y = darr(self.p['XData']).reshape(-1), darr(self.p['YData']).reshape(-1)
        ok = np.isfinite(x) & np.isfinite(y)
        x, y = x[ok], y[ok]
        nb = darr(self.p['NumBins']).reshape(-1)
        nx, ny = (int(nb[0]), int(nb[0])) if nb.size == 1 else (int(nb[0]), int(nb[1]))
        xl = darr(self.p['XLimits']).reshape(-1) if numel(self.p['XLimits']) == 2 else np.array([x.min(), x.max()]) if x.size else np.array([0.0, 1.0])
        yl = darr(self.p['YLimits']).reshape(-1) if numel(self.p['YLimits']) == 2 else np.array([y.min(), y.max()]) if y.size else np.array([0.0, 1.0])
        if xl[1] <= xl[0]:
            xl = xl + np.array([-0.5, 0.5])
        if yl[1] <= yl[0]:
            yl = yl + np.array([-0.5, 0.5])
        H, xe, ye = np.histogram2d(x, y, bins=[nx, ny], range=[xl, yl])
        self.p['Values'] = H.T
        show_empty = bool(num(self.p['ShowEmptyBins'])) if not is_str(self.p['ShowEmptyBins']) else py_str(self.p['ShowEmptyBins']).lower() == 'on'
        ii, jj = np.nonzero(H > 0) if not show_empty else np.nonzero(np.ones_like(H, bool))
        P = GB.Patch(ax)
        verts, faces, cdata = [], [], []
        for k, (i, j) in enumerate(zip(ii, jj)):
            base = len(verts)
            verts += [[xe[i], ye[j]], [xe[i + 1], ye[j]], [xe[i + 1], ye[j + 1]], [xe[i], ye[j + 1]]]
            faces.append([base + 1, base + 2, base + 3, base + 4])
            cdata.append(H[i, j])
        if faces:
            P.props['Vertices'] = np.array(verts, float)
            P.props['Faces'] = np.array(faces, float)
            P.props['FaceVertexCData'] = np.array(cdata, float).reshape(-1, 1)
        P.props['FaceColor'] = 'flat'
        P.props['EdgeColor'] = 'none'
        P.props['FaceAlpha'] = float(num(self.p['FaceAlpha']))
        self.parts = [P]
        ax.props['XLim'] = np.array([[xe[0], xe[-1]]])
        ax.props['YLim'] = np.array([[ye[0], ye[-1]]])
        ax.touch()


@bi('binscatter')
def binscatter(nargout, *args):
    """h = binscatter(x, y), binscatter(x, y, N), binscatter(..., 'XLimits', xl, 'YLimits', yl): a scatter plot of many points as bins coloured by how many fall in each."""
    G = _g()
    a = list(args)
    ax, a = G.split_axes_arg(a)
    x = darr(a.pop(0), 'binscatter').reshape(-1)
    y = darr(a.pop(0), 'binscatter').reshape(-1)
    if x.size != y.size:
        raise err('MATLAB:binscatter:size', 'x and y have as many values each.', 'binscatter')
    nb = None
    if a and not is_str(a[0]):
        nb = darr(a.pop(0)).reshape(-1)
    o = dict((k.lower(), v) for k, v in _pairs(a, 'binscatter'))
    if nb is None:
        n = int(np.count_nonzero(np.isfinite(x) & np.isfinite(y)))
        nb = np.array([float(min(max(int(round(math.sqrt(n) / 2)), 10), 300))])
    ax = G.newplot(ax)
    props = {'XData': x.reshape(-1, 1), 'YData': y.reshape(-1, 1), 'NumBins': nb.reshape(1, -1), 'XLimits': o.get('xlimits', EMPTY()),
             'YLimits': o.get('ylimits', EMPTY()), 'Values': EMPTY(), 'ShowEmptyBins': o.get('showemptybins', Char.of('off')), 'FaceAlpha': o.get('facealpha', 1.0)}
    h = Binscatter(ax, props)
    h.draw()
    R._builtin('colorbar', ax)
    return h if nargout else None


# ---- parallelplot ------------------------------------------------------------------------------------------------------------------------

class ParallelPlot(Chart):
    cls = 'matlab.graphics.chart.ParallelCoordinatesPlot'
    KEYS = ('Data', 'CoordinateTickLabels', 'GroupData', 'DataNormalization', 'Title', 'LineWidth', 'Color')

    def draw(self):
        GB = _gb()
        ax = self.fresh_axes()
        D = np.asarray(darr(self.p['Data']), float)
        n, p = D.shape
        norm = py_str(self.p['DataNormalization']).lower()
        lo, hi = np.nanmin(D, axis=0), np.nanmax(D, axis=0)
        if norm == 'range':
            Z = (D - lo) / np.where(hi > lo, hi - lo, 1)
        elif norm == 'zscore':
            Z = (D - np.nanmean(D, axis=0)) / np.where(np.nanstd(D, axis=0, ddof=1) > 0, np.nanstd(D, axis=0, ddof=1), 1)
        elif norm == 'center':
            Z = D - np.nanmean(D, axis=0)
        elif norm == 'scale':
            Z = D / np.where(np.nanstd(D, axis=0, ddof=1) > 0, np.nanstd(D, axis=0, ddof=1), 1)
        else:
            Z = D
        xs = np.arange(1, p + 1, dtype=float)
        g = self.p['GroupData']
        if numel(g):
            names, order = _group_values(g, n)
        else:
            names, order = [''] * n, ['']
        cols = np.asarray(darr(self.p['Color']), float) if numel(self.p['Color']) else np.array(_gb().COLOR_ORDER, float)
        for gi, grp in enumerate(order):
            rows = [i for i in range(n) if names[i] == grp]
            if not rows:
                continue
            xx = np.concatenate([np.append(xs, np.nan) for _ in rows])
            yy = np.concatenate([np.append(Z[i], np.nan) for i in rows])
            L = GB.Line(ax)
            L.props['XData'], L.props['YData'] = xx.reshape(1, -1), yy.reshape(1, -1)
            L.props['Color'] = tuple(cols[gi % cols.shape[0]])
            L.props['LineWidth'] = float(num(self.p['LineWidth']))
            L.props['DisplayName'] = grp
        labels = _texts(self.p['CoordinateTickLabels'])
        R._builtin('xticks', ax, xs.reshape(1, -1))
        R._builtin('xticklabels', ax, Cell.of_list([Char.of(s) for s in labels]))
        ax.props['XLim'] = np.array([[0.75, p + 0.25]])
        ax.props['XLimMode'] = 'manual'
        ax.props['XGrid'] = True
        if norm == 'range':
            # each coordinate's own scale, at its bottom and top
            for j in range(p):
                for v, yv, va in ((lo[j], 0.0, 'top'), (hi[j], 1.0, 'bottom')):
                    t = GB.Text(ax)
                    t.props['String'] = f'{v:.4g}'
                    t.props['Position'] = np.array([[xs[j], yv, 0.0]])
                    t.props['HorizontalAlignment'] = 'center'
                    t.props['VerticalAlignment'] = va
                    t.props['FontSize'] = 8.0
            ax.props['YLim'] = np.array([[-0.08, 1.08]])
            ax.props['YLimMode'] = 'manual'
            R._builtin('yticks', ax, np.zeros((1, 0)))
        if numel(self.p['GroupData']) and len(order) > 1:
            R._builtin('legend', ax, Cell.of_list([Char.of(s) for s in order]))
        R._builtin('title', ax, self.p['Title'])
        ax.touch()


@bi('parallelplot')
def parallelplot(nargout, *args):
    """p = parallelplot(data), parallelplot(tbl), parallelplot(..., 'GroupData', g, 'CoordinateVariables', vars, 'DataNormalization', n): each row a line across the coordinates (columns), each coordinate scaled to its range unless asked."""
    G = _g()
    from .tables import Table
    a = list(args)
    parent = None
    if a and G.is_axes(a[0]):
        parent = a.pop(0)
    d0 = a.pop(0)
    o = dict((k.lower(), v) for k, v in _pairs(a, 'parallelplot'))
    group = o.pop('groupdata', EMPTY())
    if isinstance(d0, Table):
        T = d0
        if 'groupvariable' in o:
            gv = py_str(o.pop('groupvariable'))
            group = T.vars[T.names.index(gv)]
        sel = T.var_index(o.pop('coordinatevariables')) if 'coordinatevariables' in o else [k for k, v in enumerate(T.vars) if type(v) is np.ndarray and v.dtype.kind in 'fiub']
        D = np.column_stack([np.asarray(T.vars[k], float).reshape(-1) for k in sel])
        labels = [T.names[k] for k in sel]
    else:
        D = np.asarray(darr(d0, 'parallelplot'), float)
        if D.ndim == 1:
            D = D.reshape(1, -1)
        labels = [str(j + 1) for j in range(D.shape[1])]
        if 'coordinatedata' in o:
            sel = [int(k) - 1 for k in darr(o.pop('coordinatedata')).reshape(-1)]
            D = D[:, sel]
            labels = [labels[k] for k in sel]
    props = {'Data': D, 'CoordinateTickLabels': o.pop('coordinateticklabels', Cell.of_list([Char.of(s) for s in labels])), 'GroupData': group,
             'DataNormalization': o.pop('datanormalization', Char.of('range')), 'Title': o.pop('title', Char.of('')), 'LineWidth': o.pop('linewidth', 1.0),
             'Color': o.pop('color', EMPTY())}
    ax = G.newplot(parent)
    h = ParallelPlot(ax, props)
    h.draw()
    return h if nargout else None


# ---- scatterhistogram ----------------------------------------------------------------------------------------------------------------------

class ScatterHistogram(Chart):
    cls = 'matlab.graphics.chart.ScatterHistogramChart'
    KEYS = ('XData', 'YData', 'GroupData', 'XLabel', 'YLabel', 'Title')

    def draw(self):
        args = [self.p['XData'], self.p['YData']]
        if numel(self.p['GroupData']):
            args += [Char.of('Group'), self.p['GroupData']]
        f = _g().gcf_()
        for c in list(f.children):
            if c.TYPE in ('axes', 'legend', 'colorbar'):
                c.delete_handle()
        h = R._builtin('scatterhist', *args)
        axs = [c for c in f.children if c.TYPE == 'axes']
        main = axs[-1] if axs else None
        if main is not None:
            R._builtin('xlabel', main, self.p['XLabel'])
            R._builtin('ylabel', main, self.p['YLabel'])
        if numel(self.p['Title']):
            R._builtin('sgtitle', self.p['Title'])
        self.ax = main
        return h


@bi('scatterhistogram')
def scatterhistogram(nargout, *args):
    """s = scatterhistogram(x, y, 'GroupData', g), scatterhistogram(tbl, xvar, yvar, 'GroupVariable', gvar): a scatter plot with the histograms of x and y beside it."""
    from .tables import Table
    a = list(args)
    xl = yl = ''
    if a and isinstance(a[0], Table):
        T = a.pop(0)
        xv, yv = py_str(a.pop(0)), py_str(a.pop(0))
        x, y = T.vars[T.names.index(xv)], T.vars[T.names.index(yv)]
        xl, yl = xv, yv
        o = dict((k.lower(), v) for k, v in _pairs(a, 'scatterhistogram'))
        g = T.vars[T.names.index(py_str(o.pop('groupvariable')))] if 'groupvariable' in o else o.pop('groupdata', EMPTY())
    else:
        x, y = a.pop(0), a.pop(0)
        o = dict((k.lower(), v) for k, v in _pairs(a, 'scatterhistogram'))
        g = o.pop('groupdata', EMPTY())
    props = {'XData': x, 'YData': y, 'GroupData': g, 'XLabel': o.pop('xlabel', Char.of(xl)), 'YLabel': o.pop('ylabel', Char.of(yl)), 'Title': o.pop('title', Char.of(''))}
    h = ScatterHistogram(None, props)
    h.draw()
    return h if nargout else None


# ---- wordcloud ---------------------------------------------------------------------------------------------------------------------------------

class WordCloud(Chart):
    cls = 'matlab.graphics.chart.WordCloudChart'
    KEYS = ('WordData', 'SizeData', 'MaxDisplayWords', 'Color', 'HighlightColor', 'Title', 'Shape')

    def draw(self):
        GB = _gb()
        ax = self.fresh_axes()
        words = _texts(self.p['WordData'])
        sizes = darr(self.p['SizeData']).reshape(-1).astype(float)
        order = np.argsort(-sizes, kind='stable')[:int(num(self.p['MaxDisplayWords']))]
        words = [words[i] for i in order]
        sizes = sizes[order]
        if not words:
            ax.props['Visible'] = False
            ax.touch()
            return
        smax, smin = sizes.max(), sizes.min()
        fs = 10 + 30 * ((sizes - smin) / (smax - smin) if smax > smin else np.ones_like(sizes))
        placed = []
        aspect = 2.0 if py_str(self.p['Shape']).lower() == 'oval' else 1.0
        col = _color(self.p['Color'])
        hcol = _color(self.p['HighlightColor'])
        nh = max(1, int(round(len(words) * 0.1)))
        for k, (w, f) in enumerate(zip(words, fs)):
            ww, hh = 0.6 * f * max(len(w), 1), 1.1 * f
            pos = None
            for step in range(4000):
                t = step * 0.25
                r = 1.2 * t
                x, y = aspect * r * math.cos(t), r * math.sin(t)
                box = (x - ww / 2, y - hh / 2, x + ww / 2, y + hh / 2)
                if all(box[2] <= b[0] or box[0] >= b[2] or box[3] <= b[1] or box[1] >= b[3] for b in placed):
                    pos = (x, y)
                    placed.append(box)
                    break
            if pos is None:
                continue
            tx = GB.Text(ax)
            tx.props['String'] = w
            tx.props['Position'] = np.array([[pos[0], pos[1], 0.0]])
            tx.props['HorizontalAlignment'] = 'center'
            tx.props['FontSize'] = float(f)
            tx.props['Color'] = hcol if k < nh else col
            tx.props['FontWeight'] = 'bold' if k < nh else 'normal'
        xs = [b[0] for b in placed] + [b[2] for b in placed]
        ys = [b[1] for b in placed] + [b[3] for b in placed]
        span = max(max(xs) - min(xs), (max(ys) - min(ys)) * 1.6, 1.0)
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        ax.props['XLim'] = np.array([[cx - span * 0.6, cx + span * 0.6]])
        ax.props['YLim'] = np.array([[cy - span * 0.6 / 1.6, cy + span * 0.6 / 1.6]])
        ax.props['XLimMode'] = ax.props['YLimMode'] = 'manual'
        ax.props['Visible'] = False
        if numel(self.p['Title']):
            R._builtin('title', ax, self.p['Title'])
            ax.title.props['Visible'] = True
        ax.touch()


@bi('wordcloud')
def wordcloud(nargout, *args):
    """wc = wordcloud(words, sizeData), wordcloud(tbl, wordVar, sizeVar), wordcloud(C) of categorical or text: words drawn at sizes by their counts or sizes, the largest highlighted."""
    G = _g()
    from .tables import Table
    from .categoricals import Categorical
    from collections import Counter
    import re
    a = list(args)
    parent = None
    if a and G.is_axes(a[0]):
        parent = a.pop(0)
    d0 = a.pop(0)
    if isinstance(d0, Table):
        wv, sv = py_str(a.pop(0)), py_str(a.pop(0))
        words = _group_values(d0.vars[d0.names.index(wv)], d0.n)[0]
        sizes = darr(d0.vars[d0.names.index(sv)]).reshape(-1)
    elif a and not is_str(a[0]):
        words = _texts(d0) if not isinstance(d0, Categorical) else _group_values(d0, numel(d0))[0]
        sizes = darr(a.pop(0)).reshape(-1)
    else:
        if isinstance(d0, Categorical):
            toks = [t for t in _group_values(d0, numel(d0))[0] if t != '<undefined>']
        else:
            text = ' '.join(_texts(d0))
            stop = set('a an and are as at be by for from has have in is it its of on or that the this to was were will with'.split())
            toks = [t.lower() for t in re.findall(r"[A-Za-zÀ-ÿ']+", text) if t.lower() not in stop and len(t) > 1]
        cnt = Counter(toks)
        words = list(cnt)
        sizes = np.array([float(cnt[w]) for w in words])
    o = dict((k.lower(), v) for k, v in _pairs(a, 'wordcloud'))
    props = {'WordData': Str(np.array([words], object)), 'SizeData': sizes.reshape(1, -1), 'MaxDisplayWords': o.pop('maxdisplaywords', 100.0),
             'Color': o.pop('color', np.array([[0.2510, 0.2510, 0.2510]])), 'HighlightColor': o.pop('highlightcolor', np.array([[0.8510, 0.3255, 0.0980]])),
             'Title': o.pop('title', Char.of('')), 'Shape': o.pop('shape', Char.of('oval'))}
    ax = G.newplot(parent)
    h = WordCloud(ax, props)
    h.draw()
    return h if nargout else None
