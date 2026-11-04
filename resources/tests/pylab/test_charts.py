"""Charts and volumes, run natively (CPython with numpy and scipy): what
each chart computes and makes (constant lines and regions and their
spanning, heatmap's counts and means, boxchart's quartiles and outliers,
swarmchart's spreading, pie and donut wedges, stackedplot's axes, plotyy,
polarhistogram and binscatter against numpy's histograms, parallelplot,
wordcloud), and the volume functions (fimplicit3 on a sphere, tetramesh,
isocaps, isonormals, smooth3 against scipy.ndimage, reducevolume,
subvolume, volumebounds, reducepatch, streamslice on a rotation, and
streamparticles). How they look is the browser test's.

    python3 test_charts.py          (from any folder)
"""
import asyncio
import math
import os
import sys
import tempfile

import numpy as np
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402
from plab.graphics_base import STORE, serialize_child  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-charts-')


def run(code):
    R.BASE.clear()
    R.take_output()
    asyncio.run(R.execute(f"cd('{TMP}');\n" + code))
    return dict(R.BASE), R.take_output()


class Checks:
    def __init__(self):
        self.n = 0
        self.failed = []

    def __call__(self, label, ok, detail=''):
        self.n += 1
        if not ok:
            self.failed.append(label)
            print(f'FAIL  {label}  {detail}')
        return ok

    def done(self):
        print(f'\n{self.n - len(self.failed)} of {self.n} checks passed')
        return 1 if self.failed else 0


C = Checks()


def a(x):
    if isinstance(x, tuple):
        parts = [np.asarray(v, dtype=float).reshape(-1) for v in x]
        return np.concatenate(parts) if parts else np.zeros(0)
    return np.asarray(x, dtype=float)


def near(label, got, want, tol=1e-10):
    g, w = a(got), a(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {np.round(g, 6).tolist() if g.size < 30 else g.shape}, want {np.round(w, 6).tolist() if w.size < 30 else w.shape}')


def same(label, got, want):
    return C(label, got == want, f'got {got!r}, want {want!r}')


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = W['e'].str() if isinstance(W['e'], Char) else str(W['e'])
    return C(f'refused: {code}', words in msg, msg)


def text(v):
    from plab.values import py_str
    if isinstance(v, str):
        return v
    return v.str() if isinstance(v, Char) else py_str(v)


def kids(ax, t=None):
    return [c for c in ax.children if c.valid and (t is None or c.TYPE == t)]


# ---- constant lines and regions ------------------------------------------------------------------------------------------------
W, _ = run("close all; plot(1:10, (1:10).^2); xl = xline(5, '--r', 'five'); yl = yline([20 50], ':', {'a', 'b'}); xr = xregion(2, 3); yr = yregion([60 70 80 90]); "
           "v = xl.Value; ty = get(xl, 'Type'); lim = xlim; ylm = ylim; nyl = numel(yl); nyr = numel(yr); xl.Value = 7; v2 = xl.Value; ls = xl.LineStyle; c = xl.Color; lab = xl.Label; "
           "tr = get(xr, 'Type'); rv = xr.Value; fa = xr.FaceAlpha;")
near('xline: its value, moved by setting Value; two ylines and two yregions', (W['v'], W['v2'], W['nyl'], W['nyr']), (5, 7, 2, 2))
same("the Type, LineSpec and label; the limits not changed by them", (text(W['ty']), text(W['ls']), a(W['c']).tolist(), text(W['lab']), a(W['lim']).tolist(), text(W['tr'])),
     ('constantline', '--', [[1.0, 0.0, 0.0]], 'five', [[1.0, 10.0]], 'constantregion'))
near('xregion: its value and see-through face', (W['rv'], W['fa']), ([2, 3], 0.3))
ax = STORE.current.props['CurrentAxes']
spans = [serialize_child(c, ax).get('span') for c in kids(ax)]
same('sent to the page as spanning a line (or patch) across the axes', sorted(s for s in spans if s), sorted(['vertical', 'horizontal', 'horizontal', 'vertical', 'horizontal', 'horizontal']))
labs = [serialize_child(c, ax).get('label') for c in kids(ax) if serialize_child(c, ax).get('span') and c.TYPE == 'line']
same('with their labels', sorted(x for x in labs if x), ['a', 'b', 'five'])

# ---- heatmap ------------------------------------------------------------------------------------------------------------------------
W, out = run("close all; T = table(categorical({'a';'b';'a';'c';'a'}), categorical({'x';'x';'y';'y';'y'}), [1;2;3;4;5], 'VariableNames', {'g', 'k', 'v'}); "
             "h = heatmap(T, 'g', 'k'); cd1 = h.ColorData; xd = h.XData; t1 = h.Title; h2 = heatmap(T, 'g', 'k', 'ColorVariable', 'v'); cd2 = h2.ColorData; "
             "h3 = heatmap({'p', 'q'}, {'r', 's', 't'}, magic(3)(:, 1:2)); h3.Title = 'Magic'; cls = class(h3); cl = h3.ColorLimits; "
             "h4 = heatmap([1 NaN; 3 4]);")
near('heatmap from a table: counts of each pair; means of a variable (NaN where none)', (W['cd1'], W['cd2']), ([[1, 1, 0], [2, 0, 1]], [[1, 2, np.nan], [4, np.nan, 4]]))
same('its labels, title and class; the colour limits from the data', ([x.str() for x in W['xd'].a.reshape(-1)], text(W['t1']), text(W['cls']), a(W['cl']).tolist()),
     (['a', 'b', 'c'], 'Count of k vs. g', 'matlab.graphics.chart.HeatmapChart', [[1.0, 9.0]]))
ax = STORE.current.props['CurrentAxes']
cell_texts = [c.props['String'] for c in kids(ax, 'text')]
same('a number in each cell, NaN shown as such', sorted(cell_texts), ['1', '3', '4', 'NaN'])

# ---- boxchart and swarmchart -----------------------------------------------------------------------------------------------------
y = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 40.0])
np.savetxt(os.path.join(TMP, 'y.txt'), y)
W, _ = run("close all; y = load('y.txt'); b = boxchart(y); q = quantile(y, [0.25 0.5 0.75]); cls = class(b); "
           "figure; b2 = boxchart(categorical({'u','v','u','v'})', [1 2 3 4]', 'Notch', 'on'); xt = xticklabels; "
           "figure; rng(3); x = [ones(1, 30) 2*ones(1, 30)]; yy = [randn(1, 30) 3+randn(1, 30)]; s = swarmchart(x, yy); sx = s.XData; sy = s.YData;")
ax = STORE.figures[1].props['CurrentAxes']
box = [c for c in kids(ax, 'patch')][0]
ys = np.asarray(box.props['YData']).reshape(-1)
q = a(W['q']).reshape(-1)
near('boxchart: the box from the first to the third quartile', (ys.min(), ys.max()), (q[0], q[2]))
lines = kids(ax, 'line')
med = [np.asarray(L.props['YData']).reshape(-1) for L in lines if L.props['LineWidth'] == 2.0][0]
outl = [L for L in lines if L.props['Marker'] != 'none']
wh = max(np.asarray(L.props['YData']).max() for L in lines if L.props['Marker'] == 'none' and L.props['LineWidth'] != 2.0)
near('the median line; the whisker to the largest value within 1.5 boxes; 40 an outlier', (med, wh, np.asarray(outl[0].props['YData']).reshape(-1)), ([q[1], q[1]], 9, [40]))
same('class; groups of a categorical labelled', (text(W['cls']), [x.str() for x in W['xt'].a.reshape(-1)]), ('matlab.graphics.chart.primitive.BoxChart', ['u', 'v']))
off = a(W['sx']).reshape(-1) - np.array([1.0] * 30 + [2.0] * 30)
C('swarmchart: each point moved sideways within half the jitter width, its y kept', np.abs(off).max() <= 0.45 + 1e-12 and np.abs(off).max() > 0.05 and np.allclose(a(W['sy']).reshape(-1), a(W['yy']).reshape(-1)), np.abs(off).max())

# ---- pie, donut, stacked, plotyy ----------------------------------------------------------------------------------------------------
W, _ = run("close all; p = piechart([1 2 3 0], {'x', 'y', 'z', 'w'}); ls = p.LabelStyle; figure; d = donutchart([3 1], 'CenterLabel', 'Total'); ir = d.InnerRadius; "
           "figure; s = stackedplot(rand(20, 3), 'Title', 'Three'); cs = class(s); figure; [ax, h1, h2] = plotyy(1:5, 1:5, 1:5, (1:5).^3); loc = get(ax(2), 'YAxisLocation');")
f1 = [f for f in STORE.figures.values() if f.valid][0]
ax = f1.props['CurrentAxes']
wedges = kids(ax, 'patch')
labels = sorted(c.props['String'] for c in kids(ax, 'text'))
same('piechart: a wedge for each value above 0, labelled with name and percent', (len(wedges), labels), (3, ['x (17%)', 'y (33%)', 'z (50%)']))
areas = []
for wpatch in wedges:
    px, py = np.asarray(wpatch.props['XData']).reshape(-1), np.asarray(wpatch.props['YData']).reshape(-1)
    areas.append(0.5 * abs(np.sum(px * np.roll(py, -1) - np.roll(px, -1) * py)))
near('the wedges\' areas in proportion to the values', np.sort(np.array(areas) / sum(areas)), np.array([1, 2, 3]) / 6, 2e-3)
f2 = [f for f in STORE.figures.values() if f.valid][1]
dax = f2.props['CurrentAxes']
r = [np.hypot(np.asarray(p.props['XData']).reshape(-1), np.asarray(p.props['YData']).reshape(-1)) for p in kids(dax, 'patch')]
C('donutchart: the wedges leave the middle empty (InnerRadius 0.6) and the center label is there', min(x.min() for x in r) > 0.59 and W['ir'] == 0.6 and any(c.props['String'] == 'Total' for c in kids(dax, 'text')), [x.min() for x in r])
f3 = [f for f in STORE.figures.values() if f.valid][2]
same('stackedplot: an axes for each column; plotyy: two axes, the second on the right', (len(f3.axes_list()), text(W['cs']), text(W['loc'])), (3, 'matlab.graphics.chart.StackedLineChart', 'right'))

# ---- polarhistogram, binscatter, parallelplot, scatterhistogram, wordcloud ------------------------------------------------------------
th = np.random.default_rng(7).random(200) * 2 * math.pi
np.savetxt(os.path.join(TMP, 'th.txt'), th)
xy = np.random.default_rng(8).standard_normal((500, 2))
np.savetxt(os.path.join(TMP, 'xy.txt'), xy)
W, _ = run("close all; th = load('th.txt'); h = polarhistogram(th, 12); v = h.Values; e = h.BinEdges; hp = polarhistogram(th, 6, 'Normalization', 'probability'); vp = hp.Values; "
           "figure; xy = load('xy.txt'); b = binscatter(xy(:, 1), xy(:, 2), 8); bv = b.Values; "
           "figure; p = parallelplot([1 10; 2 20; 3 30; 4 40], 'GroupData', [1; 1; 2; 2]); "
           "figure; sh = scatterhistogram(xy(:, 1), xy(:, 2)); shc = class(sh); "
           "figure; wc = wordcloud({'alpha', 'beta', 'gamma'}, [3 2 1]); wcc = class(wc); figure; wc2 = wordcloud('the cat sat on the mat the cat ran'); wd = wc2.WordData; ws = wc2.SizeData;")
near('polarhistogram: numpy.histogram of the angles over 12 bins from 0 to 2*pi; probability adds to 1', (W['v'], W['e'], np.sum(a(W['vp']))),
     (np.histogram(th, bins=np.linspace(0, 2 * math.pi, 13))[0].reshape(1, -1), np.linspace(0, 2 * math.pi, 13).reshape(1, -1), 1.0))
same('in polar axes, a wedge for each bin (the second histogram in place of the first)', (STORE.figures[1].props['CurrentAxes'].kind, len(kids(STORE.figures[1].props['CurrentAxes'], 'patch'))), ('polar', 6))
H = np.histogram2d(xy[:, 0], xy[:, 1], bins=8, range=[[xy[:, 0].min(), xy[:, 0].max()], [xy[:, 1].min(), xy[:, 1].max()]])[0]
near('binscatter: numpy.histogram2d over the data\'s limits', W['bv'], H.T)
pax = [f for f in STORE.figures.values() if f.valid][2].props['CurrentAxes']
pl = kids(pax, 'line')
yy = np.concatenate([np.asarray(L.props['YData']).reshape(-1) for L in pl])
same('parallelplot: a line for each group, each coordinate scaled to 0..1', (len(pl), float(np.nanmin(yy)), float(np.nanmax(yy))), (2, 0.0, 1.0))
same('scatterhistogram and wordcloud classes', (text(W['shc']), text(W['wcc'])), ('matlab.graphics.chart.ScatterHistogramChart', 'matlab.graphics.chart.WordCloudChart'))
words = dict(zip([str(x) for x in W['wd'].a.reshape(-1)], a(W['ws']).reshape(-1)))
same('wordcloud counts the words of a text, leaving out the common short ones', (words.get('cat'), words.get('mat'), 'the' in words), (2.0, 1.0, False))
wax = [f for f in STORE.figures.values() if f.valid][4].props['CurrentAxes']
sizes = {c.props['String']: c.props['FontSize'] for c in kids(wax, 'text')}
C('the largest size has the largest font', sizes['alpha'] > sizes['beta'] > sizes['gamma'], sizes)

# ---- volumes ----------------------------------------------------------------------------------------------------------------------------
W, _ = run("close all; fs = fimplicit3(@(x, y, z) x.^2 + y.^2 + z.^2 - 4, [-3 3]); v = fs.Vertices; "
           "figure; X = [0 0 0; 1 0 0; 0 1 0; 0 0 1; 1 1 1]; T = [1 2 3 4; 2 3 4 5]; h = tetramesh(T, X); nt = numel(h); "
           "[x, y, z] = meshgrid(linspace(-2, 2, 15), linspace(-2, 2, 13), linspace(-2, 2, 11)); V = x.^2 + y.^2 + z.^2; "
           "fv = isocaps(x, y, z, V, 5, 'enclose', 'below'); cv = fv.vertices; cc = fv.facevertexcdata; "
           "iso = isosurface(x, y, z, V, 3); n = isonormals(x, y, z, V, iso.vertices); iv = iso.vertices; "
           "W3 = rand(6, 5, 4); S = smooth3(W3); G = smooth3(W3, 'gaussian', [3 3 3], 1); "
           "[nx, ny, nz, nv] = reducevolume(x, y, z, V, [2 3 2]); sv = subvolume(x, y, z, V, [NaN 0 NaN NaN 0 1]); vb = volumebounds(x, y, z, V); "
           "rp = reducepatch(iso, 0.3); nf0 = size(iso.faces, 1); nf1 = size(rp.faces, 1); rv = rp.vertices;")
r = np.sqrt((a(W['v']) ** 2).sum(axis=1))
C('fimplicit3: the vertices of x^2 + y^2 + z^2 = 4 lie on the sphere of radius 2', np.abs(r - 2).max() < 0.05 and r.size > 100, np.abs(r - 2).max())
same('tetramesh: a patch for each tetrahedron', W['nt'], 2.0)
cv = a(W['cv'])
on_face = np.isclose(np.abs(cv), 2).any(axis=1)
C('isocaps: the caps lie on the volume\'s faces where V is below 5 (inside the sphere of radius sqrt 5 that the box cuts)', cv.size and on_face.all() and (a(W['cc']).reshape(-1) <= 5 + 1e-9).all(), cv[:3])
nrm = a(W['n'])
iv = a(W['iv'])
cosang = np.sum(-nrm * iv, axis=1) / (np.linalg.norm(nrm, axis=1) * np.linalg.norm(iv, axis=1))
C('isonormals: pointing to lower values, here towards the centre', np.min(cosang) > 0.95, np.min(cosang))
W3 = a(W['W3'])
near("smooth3 'box': scipy.ndimage's mean of each 3-by-3-by-3 with the edges repeated", W['S'], ndimage.uniform_filter(W3, 3, mode='nearest'), 1e-12)
g = np.exp(-np.arange(-1, 2) ** 2 / 2)
k = np.einsum('i,j,k->ijk', g, g, g)
near("smooth3 'gaussian'", W['G'], ndimage.correlate(W3, k / k.sum(), mode='nearest'), 1e-12)
V = a(W['nv'])
near('reducevolume: every second x and z and third y; subvolume within x <= 0 and 0 <= z <= 1', (np.shape(W['nv']), np.shape(W['sv'])), ((5, 8, 6), (13, 8, 3)))
near('volumebounds', W['vb'], [[-2, 2, -2, 2, -2, 2, 0, 12]])
rv = a(W['rv'])
C('reducepatch: fewer faces (about 30 % of them), the vertices still near the surface', W['nf1'] < W['nf0'] * 0.5 and W['nf1'] >= W['nf0'] * 0.25 and np.abs(np.linalg.norm(rv, axis=1) - math.sqrt(3)).max() < 0.25,
  (W['nf0'], W['nf1']))
W, _ = run("close all; [X, Y] = meshgrid(-2:0.1:2); U = -Y; V = X; [vs, as] = streamslice(X, Y, U, V); n = numel(vs); L1 = vs{1}; h = streamslice(X, Y, U, V); nh = numel(h); "
           "xy = stream2(X, Y, U, V, 1, 0); sp = streamparticles(xy, 7); px = sp.XData;")
L1 = a(W['L1'])
rr = np.hypot(L1[:, 0], L1[:, 1])
C('streamslice on a rotation: many lines, each going round at a nearly constant radius', W['n'] > 5 and (rr.max() - rr.min()) / rr.mean() < 0.05, (W['n'], rr.min(), rr.max()))
C('streamslice draws lines and arrows; streamparticles puts markers along the line', W['nh'] > W['n'] and 5 <= np.size(W['px']) <= 9, (W['nh'], np.size(W['px'])))
raises("streamslice(rand(3,3,3), rand(3,3,3), rand(3,3,3))", 'streamslice(X, Y, U, V)')
raises("fimplicit3('x^2')", 'function handle')

sys.exit(C.done())
