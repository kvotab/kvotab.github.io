"""Axis limits and ticks chosen automatically, as the page draws them:
limits round out to the ticks around the data (images and surfaces in
image mode stay tight); ticks are 1, 2 or 5 times a power of ten, at most
about one per 30 pixels and eleven in all."""
import math

import numpy as np

F64 = np.float64


def nice_step(span, maxn):
    if span <= 0 or not math.isfinite(span):
        return 1.0
    raw = span / max(maxn - 1, 1)
    p = 10.0 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        step = m * p
        if span / step <= maxn - 1 + 1e-9:
            if m == 2.5 and (p < 1 and False):
                continue
            return step
    return 10 * p


def nice_ticks(lo, hi, maxn=11):
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        return [lo] if math.isfinite(lo) else []
    step = nice_step(hi - lo, maxn)
    start = math.ceil(lo / step - 1e-9) * step
    out = []
    k = 0
    while True:
        v = start + k * step
        if v > hi + step * 1e-9:
            break
        out.append(0.0 if abs(v) < step * 1e-10 else round(v / step) * step)
        k += 1
        if k > 1000:
            break
    return out


def log_ticks(lo, hi):
    if lo <= 0 or hi <= 0:
        return []
    a = math.floor(math.log10(lo) + 1e-9)
    b = math.ceil(math.log10(hi) - 1e-9)
    n = b - a
    step = 1 if n <= 10 else int(math.ceil(n / 10))
    return [10.0 ** e for e in range(a, b + 1, step) if lo * (1 - 1e-9) <= 10.0 ** e <= hi * (1 + 1e-9)]


def axis_pixels(ax, which):
    f = ax.figure()
    pos = np.asarray(ax.props['Position'], float).reshape(-1)
    if f is None:
        return 400.0
    fp = np.asarray(f.props['Position'], float).reshape(-1)
    if which == 'X':
        return max(20.0, fp[2] * pos[2])
    if which == 'Y':
        return max(20.0, fp[3] * pos[3])
    return max(20.0, fp[3] * pos[3] * 0.7)


def max_ticks(px, is3d=False):
    n = int(px // 30) + 1
    return max(3, min(11 if not is3d else 7, n))


def _finite_range(a):
    a = np.asarray(a, float).reshape(-1)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return None
    return float(a.min()), float(a.max())


def _pos_range(a):
    a = np.asarray(a, float).reshape(-1)
    a = a[np.isfinite(a) & (a > 0)]
    if a.size == 0:
        return None
    return float(a.min()), float(a.max())


def data_bounds(ax):
    """{'X': (lo, hi) or None, ...} and which axes must stay tight."""
    from .graphics_base import Series
    b = {'X': [], 'Y': [], 'Z': []}
    tight = {'X': False, 'Y': False, 'Z': False}
    logs = {k: ax.props[k + 'Scale'] == 'log' for k in 'XYZ'}

    def add(k, a):
        r = _pos_range(a) if logs[k] else _finite_range(a)
        if r is not None:
            b[k].append(r)
    for c in ax.children:
        if not c.valid or getattr(c, 'hidden', False):
            continue
        p = c.props
        t = c.TYPE
        if t == 'line':
            add('X', p['XData'])
            add('Y', p['YData'])
            if np.size(p['ZData']):
                add('Z', p['ZData'])
        elif t == 'surface':
            add('X', p['XData'])
            add('Y', p['YData'])
            add('Z', p['ZData'])
        elif t == 'patch':
            if np.size(p['Vertices']):
                v = np.asarray(p['Vertices'], float)
                add('X', v[:, 0])
                add('Y', v[:, 1])
                if v.shape[1] > 2:
                    add('Z', v[:, 2])
            else:
                add('X', p['XData'])
                add('Y', p['YData'])
                if np.size(p['ZData']):
                    add('Z', p['ZData'])
        elif t == 'image':
            cd = p['CData']
            sh = np.shape(cd.a if hasattr(cd, 'a') else cd)
            if len(sh) >= 2 and sh[0] and sh[1]:
                xd = np.asarray(p['XData'], float).reshape(-1)
                yd = np.asarray(p['YData'], float).reshape(-1)
                nx, ny = sh[1], sh[0]
                dx = (xd[-1] - xd[0]) / (nx - 1) if nx > 1 else 1.0
                dy = (yd[-1] - yd[0]) / (ny - 1) if ny > 1 else 1.0
                b['X'].append((min(xd[0], xd[-1]) - abs(dx) / 2, max(xd[0], xd[-1]) + abs(dx) / 2))
                b['Y'].append((min(yd[0], yd[-1]) - abs(dy) / 2, max(yd[0], yd[-1]) + abs(dy) / 2))
                tight['X'] = tight['Y'] = True
        elif isinstance(c, Series):
            k = c.kind
            if k in ('bar',):
                x = np.asarray(p['XData'], float).reshape(-1)
                y = np.asarray(c.extra.get('top', p['YData']), float)
                base = c.extra.get('bottom')
                w = c.extra.get('width', 0.8)
                xs = c.extra.get('xs', x)
                xr = (float(np.nanmin(xs)) - w / 2, float(np.nanmax(xs)) + w / 2) if np.size(xs) else None
                yv = np.concatenate([np.asarray(y, float).reshape(-1), np.asarray(base, float).reshape(-1) if base is not None else [p['BaseValue']]])
                yr = _finite_range(yv)
                if p['Horizontal']:
                    if xr:
                        b['Y'].append(xr)
                    if yr:
                        b['X'].append(yr)
                else:
                    if xr:
                        b['X'].append(xr)
                    if yr:
                        b['Y'].append(yr)
            elif k == 'histogram':
                e = np.asarray(c.extra.get('edges', []), float).reshape(-1)
                v = np.asarray(c.extra.get('values', []), float).reshape(-1)
                if e.size:
                    if p['Horizontal']:
                        b['Y'].append((e[0], e[-1]))
                        b['X'].append((0.0, float(v.max()) if v.size else 1.0))
                    else:
                        b['X'].append((e[0], e[-1]))
                        b['Y'].append((0.0, float(v.max()) if v.size else 1.0))
            elif k in ('stem', 'stair', 'area', 'scatter', 'bubblechart', 'errorbar', 'quiver', 'contour'):
                add('X', p['XData'])
                add('Y', p['YData'])
                if np.size(p['ZData']) and k in ('scatter', 'bubblechart', 'stem', 'quiver'):
                    add('Z', p['ZData'])
                if k == 'stem':
                    b['Y'].append((p['BaseValue'], p['BaseValue']))
                if k == 'area':
                    b['Y'].append((p['BaseValue'], p['BaseValue']))
                    top = c.extra.get('top')
                    if top is not None:
                        add('Y', top)
                if k == 'errorbar':
                    y = np.asarray(p['YData'], float).reshape(-1)
                    for key, sign in (('YNegativeDelta', -1), ('YPositiveDelta', 1)):
                        d = p.get(key)
                        if d is not None and np.size(d):
                            add('Y', y + sign * np.asarray(d, float).reshape(-1))
                    x = np.asarray(p['XData'], float).reshape(-1)
                    for key, sign in (('XNegativeDelta', -1), ('XPositiveDelta', 1)):
                        d = p.get(key)
                        if d is not None and np.size(d):
                            add('X', x + sign * np.asarray(d, float).reshape(-1))
                if k == 'quiver':
                    x = np.asarray(p['XData'], float)
                    y = np.asarray(p['YData'], float)
                    u = np.asarray(p['UData'], float) * c.extra.get('scale', 1.0)
                    v = np.asarray(p['VData'], float) * c.extra.get('scale', 1.0)
                    add('X', x + u)
                    add('Y', y + v)
                if k == 'contour':
                    tight['X'] = tight['Y'] = True
                    if c.extra.get('is3d'):
                        add('Z', p['ZData'])
            elif k == 'pie':
                b['X'].append((-1.0, 1.0))
                b['Y'].append((-1.0, 1.0))
                tight['X'] = tight['Y'] = True
    out = {}
    for k in 'XYZ':
        if logs[k] and b[k]:
            # a log axis shows positive values only: ranges reaching 0 (a bar's
            # base, an area's) start a tenth below the smallest positive end
            ends = [v for r in b[k] for v in r if v > 0]
            low = min(ends) / 10 if ends else None
            b[k] = [(r[0] if r[0] > 0 else low, r[1]) for r in b[k] if r[1] > 0 and low is not None]
        if b[k]:
            out[k] = (min(r[0] for r in b[k]), max(r[1] for r in b[k]))
        else:
            out[k] = None
    return out, tight


def _aligned(lo, hi, px, log, tight, is3d=False):
    if lo is None:
        return [1.0, 10.0] if log else [0.0, 1.0]
    if log:
        if not (lo > 0 and hi > 0):
            return [0.1, 1.0] if not hi > 0 else [hi / 100, hi * 10]
        if lo == hi:
            return [lo / 10, hi * 10]
        if tight:
            return [lo, hi]
        return [10.0 ** math.floor(math.log10(lo) + 1e-9), 10.0 ** math.ceil(math.log10(hi) - 1e-9)]
    if lo == hi:
        if lo == 0:
            return [-1.0, 1.0]
        d = abs(lo) * 0.1 if abs(lo) > 1 else 1.0
        if abs(lo) >= 1:
            return [lo - 1, hi + 1] if abs(lo) < 10 else [lo - d, hi + d]
        return [lo - 1, hi + 1]
    if tight:
        return [lo, hi]
    n = max_ticks(px, is3d)
    step = nice_step(hi - lo, n)
    a = math.floor(lo / step + 1e-9) * step
    b = math.ceil(hi / step - 1e-9) * step
    if (b - a) / step > n - 1 + 1e-9:
        step = nice_step(b - a, n)
        a = math.floor(lo / step + 1e-9) * step
        b = math.ceil(hi / step - 1e-9) * step
    return [a, b]


def auto_limits(ax):
    bounds, tight = data_bounds(ax)
    is3d = ax.is3d()
    axis_tight = getattr(ax, 'axis_tight', False)
    out = {}
    for k in 'XYZ':
        r = bounds[k]
        lo, hi = (r if r is not None else (None, None))
        log = ax.props[k + 'Scale'] == 'log'
        lim = _aligned(lo, hi, axis_pixels(ax, k), log, tight[k] or axis_tight, is3d)
        out[k + 'Lim'] = lim
    out['bounds'] = {k: (list(bounds[k]) if bounds[k] else None) for k in 'XYZ'}
    out['tight'] = tight
    return out


def auto_ticks(ax, which):
    lim = ax.get_value(which + 'Lim').reshape(-1)
    lo, hi = float(lim[0]), float(lim[1])
    if ax.props[which + 'Scale'] == 'log':
        return log_ticks(lo, hi)
    return nice_ticks(lo, hi, max_ticks(axis_pixels(ax, which), ax.is3d()))


def tick_labels(ticks, scale='linear'):
    """Tick labels and the exponent shown at the axis' end (None when the
    labels carry the numbers whole)."""
    if not ticks:
        return [], None
    if scale == 'log':
        return [f'10^{{{int(round(math.log10(t)))}}}' if t > 0 else '0' for t in ticks], None
    m = max(abs(t) for t in ticks)
    exp = None
    vals = list(ticks)
    if m > 0:
        e = int(math.floor(math.log10(m)))
        if e >= 4 or e <= -4:
            exp = e
            vals = [t / 10.0 ** e for t in ticks]
    step = min((abs(b - a) for a, b in zip(vals, vals[1:])), default=1.0)
    dec = 0
    while dec < 10 and abs(round(step * 10 ** dec) - step * 10 ** dec) > 1e-6 * max(1.0, step * 10 ** dec):
        dec += 1
    labels = []
    for v in vals:
        s = f'{v:.{dec}f}'
        if '.' in s:
            s = s.rstrip('0').rstrip('.')
        if s == '-0':
            s = '0'
        labels.append(s)
    return labels, exp


def auto_clim(ax):
    """The color limits from the data colored through the colormap."""
    from .graphics_base import Series
    lo, hi = math.inf, -math.inf
    for c in ax.children:
        if not c.valid:
            continue
        p = c.props
        cd = None
        if c.TYPE == 'surface':
            cd = p['CData'] if np.size(p['CData']) else p['ZData']
        elif c.TYPE == 'image' and p['CDataMapping'] == 'scaled':
            cd = p['CData']
        elif c.TYPE == 'patch':
            cd = p['FaceVertexCData'] if np.size(p['FaceVertexCData']) else p['CData']
        elif isinstance(c, Series) and c.kind in ('scatter', 'bubblechart', 'contour'):
            cd = p['CData'] if c.kind != 'contour' else c.extra.get('levels')
            if c.kind == 'contour':
                z = np.asarray(p['ZData'], float)
                cd = z
        if cd is None or not np.size(cd) or hasattr(cd, 'a'):
            continue
        a = np.asarray(cd, float)
        if a.ndim == 3 and a.shape[2] == 3:
            continue
        a = a[np.isfinite(a)]
        if a.size:
            lo = min(lo, float(a.min()))
            hi = max(hi, float(a.max()))
    if lo == math.inf:
        return [0.0, 1.0]
    if lo == hi:
        return [lo - 1, hi + 1] if True else [lo, hi]
    return [lo, hi]
