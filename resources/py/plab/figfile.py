"""Figure files (.fig): a MAT-file whose variable hgS_070000 (hgS_050200 in
older ones) holds the figure as a tree of structs, one for each object:

    type        'figure', 'axes', 'line', 'text', 'uicontrol', ...
    handle      its handle number when it was saved
    properties  its properties, by name
    children    a struct array of the same, its children, the first made first
    special     the places among the children of objects its parent made
                with it, such as an axes' title and labels

load() makes the objects again and save() writes them. An axes' Title,
XLabel, YLabel and ZLabel properties hold the handle numbers of the texts
among its children that they are (as GNU Octave's struct2hdl finds them).
Groups of older releases (hggroup, graph2d.lineseries, specgraph's groups)
are made of what they hold. Files saved with 'compact' in R2014b or later
keep their objects only in that release's own form, which is not read.

The layout is the commonly known one (SciPy's loadmat shows it, Octave reads
and writes it); nothing here was learned from files MATLAB wrote.
"""
import re

import numpy as np

from .values import MError, Char, Cell, Struct, FH, EMPTY, py_str
from .graphics_base import (STORE, Figure, Axes, Line, Surface, Patch, Image, Text, Light, Series, Legend, Colorbar, HArr,
                            GObj, export_value)
from . import uiobjects as U
from . import runtime as R

ROOT_NAME = re.compile(r'hgS_\d+$')
NEW_FORM = re.compile(r'hgM_\d+$')

_PLAIN = {'axes': Axes, 'line': Line, 'text': Text, 'surface': Surface, 'patch': Patch, 'image': Image, 'light': Light,
          'uicontrol': U.UIControl, 'uipanel': U.UIPanel, 'uibuttongroup': U.UIButtonGroup, 'uitable': U.UITable,
          'uitabgroup': U.UITabGroup, 'uitab': U.UITab, 'uimenu': U.UIMenu, 'uicontextmenu': U.UIContextMenu,
          'uitoolbar': U.UIToolbar, 'uipushtool': U.UIPushTool, 'uitoggletool': U.UIToggleTool}
# what older releases kept as objects of their own, made as what they draw
_OLD = {'graph2d.lineseries': Line, 'graph3d.surfaceplot': Surface}
_SERIES = ('bar', 'stem', 'stair', 'area', 'errorbar', 'scatter', 'bubblechart', 'histogram', 'contour', 'quiver')
_LABELS = ('Title', 'XLabel', 'YLabel', 'ZLabel')
# set before the rest: what the other values are in
_FIRST = ('style', 'units', 'fontunits')
# never set from a file: the object's place in the tree, the read-only, what is set apart
_SKIP = {'parent', 'children', 'type', 'beingdeleted', 'number', 'currentpoint', 'currentcharacter', 'currentkey',
         'currentmodifier', 'selectiontype', 'currentobject', 'extent', 'filename', 'integerhandle', 'legend'}
# properties that name another object by its handle number
_REFS = {'uicontextmenu': 'UIContextMenu', 'currentaxes': 'CurrentAxes', 'selectedobject': 'SelectedObject',
         'selectedtab': 'SelectedTab'}
# a label's own place is the axes' to choose
_LABEL_LAYOUT = {'position', 'units', 'horizontalalignment', 'verticalalignment', 'rotation', 'extent', 'parent',
                 'children', 'type', 'beingdeleted'}


# ---- reading ---------------------------------------------------------------------------------------

class _Load:
    def __init__(self, path):
        self.path = path
        self.made = {}          # handle number in the file -> the object made for it
        self.refs = []          # (object, property, handle number), set when all are made
        self.links = []         # legends and colorbars: (kind, figure, properties)
        self.created = []       # in the order made, for their CreateFcn
        self.skipped = {}       # types not made, and how many
        self.figures = []


def _nodes(v):
    """The structs of a struct array, in order."""
    if type(v) is not Struct or v.size == 0:
        return []
    return [{k: v.f[k].reshape(-1, order='F')[i] for k in v.f} for i in range(v.size)]


def _text(v):
    try:
        return py_str(v)
    except Exception:
        return ''


def _num(v):
    try:
        a = np.asarray(v, float).reshape(-1)
        return float(a[0]) if a.size else None
    except Exception:
        return None


def _nums(v):
    try:
        return [float(x) for x in np.asarray(v, float).reshape(-1)]
    except Exception:
        return []


def _props(node):
    """(name, value) of a node's properties, what the others are in first."""
    p = node.get('properties')
    if type(p) is not Struct or p.size != 1:
        return []
    items = [(k, p.f[k].reshape(-1)[0]) for k in p.f]
    first = sorted((kv for kv in items if kv[0].lower() in _FIRST), key=lambda kv: _FIRST.index(kv[0].lower()))
    return first + [kv for kv in items if kv[0].lower() not in _FIRST]


def _set(obj, k, v):
    try:
        obj.setprop(k, v)
    except Exception:
        pass        # a property this object does not have here, or a value it does not take


def _appdata(obj, v):
    if type(v) is not Struct or v.size != 1:
        return
    d = getattr(obj, 'appdata', None)
    if d is None:
        try:
            obj.appdata = d = {}
        except AttributeError:
            return
    for k in v.f:
        d[k] = v.f[k].reshape(-1)[0]


def _build(node, parent, ctx, visible=None):
    t = _text(node.get('type')).lower()
    kids = _nodes(node.get('children'))
    special = {int(i) for i in _nums(node.get('special')) if i == int(i)}
    props = _props(node)
    tag = next((_text(v) for k, v in props if k.lower() == 'tag'), '')
    if t == 'root':
        for k in kids:
            _build(k, None, ctx, visible)
        return None
    if t == 'figure':
        from .builtins.graphics import new_figure
        obj = new_figure()
        obj.props['FileName'] = ctx.path
        ctx.figures.append(obj)
    elif parent is None:
        # an object saved without its figure goes into the current one (an axes) or its axes
        from .builtins.graphics import gcf_, gca_
        parent = gcf_() if t in ('axes', 'uicontrol', 'uipanel', 'uibuttongroup', 'uimenu', 'uitoolbar') else gca_()
        return _build(node, parent, ctx, visible)
    elif t in ('legend', 'colorbar', 'scribe.legend', 'scribe.colorbar') or (t == 'axes' and tag.lower() in ('legend', 'colorbar')):
        ctx.links.append(('legend' if 'legend' in (t + tag.lower()) else 'colorbar', parent, props))
        return None
    elif t in _PLAIN:
        obj = _PLAIN[t](parent)
    elif t in _OLD:
        obj = _OLD[t](parent)
    elif t in _SERIES:
        obj = Series(parent, t)
    elif t == 'specgraph.scattergroup':
        # a scatter of an older release: markers alone
        obj = Line(parent)
        obj.props['LineStyle'] = 'none'
        obj.props['Marker'] = 'o'
    elif t in ('hggroup', 'hgtransform') or t.startswith(('specgraph.', 'graph2d.', 'graph3d.')):
        # a group: what it holds belongs to its parent here
        if not kids:
            ctx.skipped[t] = ctx.skipped.get(t, 0) + 1
        for k in kids:
            _build(k, parent, ctx)
        return None
    else:
        ctx.skipped[t] = ctx.skipped.get(t, 0) + 1
        return None
    h = _num(node.get('handle'))
    if h is not None:
        ctx.made[h] = obj
    labels = {}
    shown = None
    for k, v in props:
        low = k.lower()
        if t == 'axes' and low in ('title', 'xlabel', 'ylabel', 'zlabel'):
            n = _num(v)
            if n is not None:
                labels[_LABELS[('title', 'xlabel', 'ylabel', 'zlabel').index(low)]] = n
            continue
        if low in _REFS:
            n = _num(v)
            if n is not None:
                ctx.refs.append((obj, _REFS[low], n))
            continue
        if low == 'applicationdata':
            _appdata(obj, v)
            continue
        if low in _SKIP:
            continue
        if t == 'figure' and low == 'visible':
            shown = v
            continue
        if t == 'specgraph.scattergroup' and low == 'sizedata':
            n = _num(v)
            if n:
                obj.props['MarkerSize'] = float(np.sqrt(n))
            continue
        _set(obj, k, v)
    if t == 'figure':
        _set(obj, 'Visible', visible if visible is not None else (shown if shown is not None else Char.of('on')))
    if t == 'histogram':
        # a histogram draws its counts and edges as kept, not its data
        vals = {k.lower(): v for k, v in props}
        for key, name in (('values', 'values'), ('binedges', 'edges')):
            if key in vals and _nums(vals[key]):
                obj.extra[name] = np.asarray(_nums(vals[key]), float).reshape(1, -1)
    # an axes' title and labels: the children its Title, XLabel ... properties name
    used = set()
    for name, n in labels.items():
        for i, kid in enumerate(kids):
            if i not in used and _num(kid.get('handle')) == n:
                used.add(i)
                try:
                    lab = obj.getprop(name)
                except MError:
                    break
                for k, v in _props(kid):
                    if k.lower() not in _LABEL_LAYOUT:
                        _set(lab, k, v)
                break
    ctx.created.append(obj)
    for i, kid in enumerate(kids):
        if i in used or (i + 1) in special:
            continue
        _build(kid, obj, ctx)
    obj.touch()
    return obj


def _link(kind, fig, props, ctx):
    """A legend or colorbar, made for its axes when that axes is there."""
    vals = {k.lower(): v for k, v in props}
    ax = ctx.made.get(_num(vals.get('axes')))
    if ax is None or ax.TYPE != 'axes':
        ax = next((a for a in reversed(fig.children) if a.TYPE == 'axes' and a.valid), None) if fig is not None else None
    if ax is None:
        ctx.skipped[kind] = ctx.skipped.get(kind, 0) + 1
        return
    if kind == 'legend':
        entries = [ctx.made[n] for n in _nums(vals.get('plotchildren')) if n in ctx.made]
        if not entries:
            entries = [c for c in reversed(ax.children) if c.valid and c.TYPE in ('line', 'surface', 'patch') + _SERIES]
        obj = Legend(ax, entries)
    else:
        obj = Colorbar(ax)
    for k, v in props:
        if k.lower() not in _SKIP and k.lower() not in ('axes', 'plotchildren', 'position', 'units'):
            _set(obj, k, v)
    obj.touch()


def load(path, visible=None):
    """The figures a .fig file holds, made again (or the objects, when it
    holds no figure)."""
    from . import matfile
    from .builtins.iofun import _fh_from_mat
    vals, problems = matfile.read(path, make_fh=_fh_from_mat)
    name = next((k for k in vals if ROOT_NAME.match(k)), None)
    if name is None:
        if any(NEW_FORM.match(k) for k in vals) or any(NEW_FORM.match(n or '') for n, _ in problems):
            raise MError('MATLAB:openfig:compactForm', "This figure file keeps its objects only in the form of R2014b and "
                         "later (saved with savefig's 'compact'), which is not read here.")
        raise MError('MATLAB:openfig:notAFigure', 'The file holds no figure: a .fig file is a MAT-file with a variable '
                     'hgS_070000.')
    root = vals[name]
    if type(root) is not Struct or root.size != 1:
        raise MError('MATLAB:openfig:notAFigure', 'The figure in the file is not a struct.')
    ctx = _Load(path)
    node = _nodes(root)[0]
    top = _build(node, None, ctx, visible)
    for kind, fig, props in ctx.links:
        _link(kind, fig, props, ctx)
    for obj, k, n in ctx.refs:
        target = ctx.made.get(n)
        if target is not None:
            _set(obj, k, target)
    from .builtins.graphics import set_current_axes
    for f in ctx.figures:
        if f.props.get('CurrentAxes') is None:
            last = next((a for a in f.children if a.TYPE == 'axes' and a.valid), None)
            if last is not None:
                set_current_axes(last)
        STORE.current = f
    from . import uievents as E
    for obj in ctx.created:
        if obj.valid:
            E.created(obj)
    if ctx.skipped:
        R.warn('MATLAB:openfig:notMade', 'Some objects in the file were not made here: '
               + ', '.join(f'{k} ({n})' for k, n in sorted(ctx.skipped.items())) + '.')
    return ctx.figures or ([top] if top is not None else [])


# ---- writing ---------------------------------------------------------------------------------------

_NEVER = {'Parent', 'Children', 'Type', 'BeingDeleted', 'CurrentPoint', 'CurrentCharacter', 'CurrentKey', 'CurrentModifier',
          'SelectionType', 'CurrentObject', 'Number', 'Title', 'XLabel', 'YLabel', 'ZLabel', 'Legend', 'Extent', 'FileName'}
_ALWAYS = {'Position', 'Units', 'XData', 'YData', 'ZData', 'CData', 'String', 'Style', 'Faces', 'Vertices', 'Value',
           'Values', 'BinEdges'}
_MISSING = object()


class _Save:
    def __init__(self):
        self.dropped = set()    # properties left out: function handles


def _same(a, b):
    try:
        if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
            A, B = np.asarray(a), np.asarray(b)
            return A.shape == B.shape and A.dtype.kind == B.dtype.kind and bool(np.array_equal(A, B, equal_nan=A.dtype.kind in 'fc'))
        if type(a) is Char or type(b) is Char:
            return type(a) is type(b) and a.a.shape == b.a.shape and a.str() == b.str()
        return type(a) is type(b) and bool(a == b)
    except Exception:
        return False


def _mat(v, ctx, name):
    """A property's value as savemat takes it: objects by their handle numbers."""
    from .builtins.iofun import to_py_mat
    if isinstance(v, GObj):
        return np.array([[v.number_value()]])
    if isinstance(v, HArr):
        return np.array([[o.number_value() if o is not None else np.nan for o in v.a.reshape(-1, order='F')]])
    if isinstance(v, FH):
        ctx.dropped.add(name)
        return None
    if isinstance(v, (Cell, Struct, Char)) or type(v) in (float, bool, complex, np.ndarray):
        return to_py_mat(v)
    if isinstance(v, str):
        return np.array([v])
    return None


def _kind(o):
    if isinstance(o, Series):
        return o.kind
    t = getattr(o, 'TYPE', None)
    return t if t in _PLAIN or t in ('figure', 'legend', 'colorbar') else None


def _saved(o, ctx):
    out = {}
    defaults = type(o).DEFAULTS
    for k, v in o.props.items():
        if k in _NEVER or k.startswith('_') or v is None:
            continue
        d = defaults.get(k, _MISSING)
        if callable(d) and not isinstance(d, FH):
            d = d()
        if k not in _ALWAYS and d is not _MISSING and _same(v, d):
            continue
        try:
            val = o.getprop(k)
        except Exception:
            val = export_value(k, v)
        m = _mat(val, ctx, k)
        if m is not None:
            out[k] = m
    appdata = getattr(o, 'appdata', None)
    if appdata:
        from .builtins.iofun import to_py_mat
        out['ApplicationData'] = {k: to_py_mat(v) for k, v in appdata.items() if not isinstance(v, (FH, GObj, HArr))}
    return out


def _array(nodes):
    dt = [('type', object), ('handle', object), ('properties', object), ('children', object), ('special', object)]
    a = np.zeros((len(nodes), 1), dtype=dt)
    for i, n in enumerate(nodes):
        for k, _ in dt:
            a[i, 0][k] = n[k]
    return a


def _node(o, ctx):
    props = _saved(o, ctx)
    kids = [c for c in reversed(o.children) if getattr(c, 'valid', False) and _kind(c) is not None]
    children = [_node(c, ctx) for c in kids]
    special = []
    if o.TYPE == 'axes':
        for name in _LABELS:
            try:
                lab = o.getprop(name)
            except MError:
                continue
            if isinstance(lab, GObj):
                props[name] = np.array([[lab.number_value()]])
                children.append(_node(lab, ctx))
                special.append(float(len(children)))
    if o.TYPE in ('legend', 'colorbar'):
        props['Axes'] = np.array([[o.axes.number_value()]])
        if o.TYPE == 'legend':
            props['PlotChildren'] = np.array([[e.number_value() for e in o.entries]]) if o.entries else np.zeros((1, 0))
    return {'type': np.array([_kind(o) or o.TYPE]), 'handle': np.array([[o.number_value()]]), 'properties': props,
            'children': _array(children), 'special': np.array([special]) if special else np.zeros((0, 0))}


def save(objs, path):
    """Objects (figures, as a rule) written as a .fig file; the properties
    left out (function handles) are returned."""
    import scipy.io as sio
    ctx = _Save()
    if len(objs) == 1:
        root = _node(objs[0], ctx)
    else:
        root = {'type': np.array(['root']), 'handle': np.array([[0.0]]), 'properties': {},
                'children': _array([_node(o, ctx) for o in objs]), 'special': np.zeros((0, 0))}
    sio.savemat(path, {'hgS_070000': root}, format='5', do_compression=True, oned_as='row')
    return sorted(ctx.dropped)
