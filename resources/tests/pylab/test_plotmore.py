"""More of the graphics core, run natively (the objects and what the page is
sent): rectangle and its curvature, hggroup and hgtransform with
makehgtform (the transformed copies drawn and the limits that follow),
'Parent' putting drawn objects in other axes or groups, rotate, refreshdata,
tick formats (and format_tick), ztickangle, polar axes' ticks, labels,
limits and directions, gplot, treelayout and treeplot, colours
(validatecolor, rgb2hex, hex2rgb, brighten), surfnorm, shrinkfaces,
isocolors and lightangle.

    python3 test_plotmore.py          (from any folder)
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

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-plotmore-')
R.STATE['home'] = TMP


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



from plab.graphics_base import serialize_axes, drawn_children  # noqa: E402
from plab.glayout import format_tick  # noqa: E402


def flat(x):
    return np.asarray(x, dtype=float).reshape(-1).tolist()


def text(v):
    from plab.values import py_str
    return py_str(v)


# ---- rectangle -----------------------------------------------------------------------------------------------------
W, _ = run("""f = figure('Visible', 'off'); r = rectangle('Position', [1 2 3 4], 'Curvature', [1 1], 'FaceColor', 'r'); c = class(r); t = r.Type;
x = r.XData; y = r.YData; r.Curvature = 0; n0 = numel(r.XData); x0 = r.XData'; r2 = rectangle; p2 = r2.Position; fc = r2.FaceColor; xl = xlim; close(f);""")
x, y = a(W['x']).reshape(-1), a(W['y']).reshape(-1)
same("rectangle: a Rectangle, Type 'rectangle'", (text(W['c']), text(W['t'])), ('matlab.graphics.primitive.Rectangle', 'rectangle'))
C('Curvature [1 1] makes the ellipse inscribed in its Position', np.allclose(((x - 2.5) / 1.5) ** 2 + ((y - 4) / 2) ** 2, 1), (x.min(), x.max(), y.min(), y.max()))
near('Curvature 0: the four corners; the default rectangle; the axes take it in', (W['n0'], W['x0'], W['p2'], float(W['xl'][0, 1]) >= 4),
     (4, [[1, 4, 4, 1]], [[0, 0, 1, 1]], 1))
same("FaceColor 'none' by default", text(W['fc']), 'none')
raises("rectangle('Position', [0 0 -1 1])", 'width and height not negative')
raises("rectangle('Curvature', 2)", 'each from 0 to 1')

# ---- groups and transforms ------------------------------------------------------------------------------------------
W, _ = run("""f = figure('Visible', 'off'); ax = gca; t = hgtransform; l = line([0 1], [0 0], 'Parent', t); in = isequal(l.Parent, t); nk = numel(t.Children);
t.Matrix = makehgtform('zrotate', pi/2); yl = ylim; ld = [l.XData; l.YData];
g = hggroup; l2 = line([5 6], [5 6], 'Parent', g); set(g, 'Visible', 'off'); xl = xlim;
a1 = subplot(1, 2, 1); a2 = subplot(1, 2, 2); h = line([0 1], [0 1], 'Parent', a1); p = patch([0 1 1], [0 0 1], 'r', 'Parent', a1); s = surface(peaks(3), 'Parent', a1);
pa = [isequal(h.Parent, a1) isequal(p.Parent, a1) isequal(s.Parent, a1)]; n2 = numel(a2.Children);""")
same('a line made with Parent, t belongs to the transform', (bool(W['in']), float(W['nk'])), (True, 1.0))
near("the transform turns what is drawn, not the line's own data; the limits follow the drawn line", (W['ld'], W['yl']), ([[0, 1], [0, 0]], [[0, 1]]), 1e-12)
C('a hidden group leaves its children out of the limits', float(a(W['xl'])[0, 1]) < 5, W['xl'])
near("'Parent' puts lines, patches and surfaces in the axes given", (W['pa'], W['n2']), ([[1, 1, 1]], 0))
W, _ = run("""f = figure('Visible', 'off'); t = hgtransform; l = line([0 1], [0 0], 'Parent', t); t.Matrix = makehgtform('translate', [2 3 0]); ax = gca;""")
from plab import graphics_base as GB  # noqa: E402
ax = W['ax']
kids = drawn_children(ax)
ser = serialize_axes(ax)
C('the page is sent the transformed copy, in place of the group', len(kids) == 1 and np.allclose(kids[0].props['XData'], [[2, 3]])
  and np.allclose(kids[0].props['YData'], [[3, 3]]) and len(ser['children']) == 1 and ser['children'][0]['type'] == 'line', [c.props.get('XData') for c in kids])
run("close all force")
W, _ = run("M = makehgtform('translate', [1 2 3], 'scale', 2); v = M*[1; 1; 1; 1]; R = makehgtform('xrotate', pi/2); w = R*[0; 1; 0; 1]; A = makehgtform('axisrotate', [0 0 1], pi/2); B = makehgtform('zrotate', pi/2); I = makehgtform;")
near('makehgtform: steps multiplied in order (the last first); rotations by the right-hand rule; axisrotate as zrotate', (W['v'], W['w'], W['A'] - W['B'], W['I']),
     ([[3], [4], [5], [1]], [[0], [0], [1], [1]], np.zeros((4, 4)), np.eye(4)), 1e-12)

# ---- rotate, refreshdata ---------------------------------------------------------------------------------------------
W, _ = run("""f = figure('Visible', 'off'); h = line([1 2], [0 0]); rotate(h, [0 0 1], 90, [1 0 0]); d = [h.XData; h.YData];
p = patch([0 1 1], [0 0 1], 'r'); rotate(p, [0 90], 180, [0 0 0]); px = p.XData'; tx = text(1, 0, 'a'); rotate(tx, [0 0 1], 90, [0 0 0]); tp = tx.Position;
x = 1:3; y = x.^2; l = plot(x, y); l.YDataSource = 'y'; y = [5 5 5]; refreshdata(f); ly = l.YData; close(f);""")
near('rotate: a line about z through a point, a patch about [0 90] (z), text by its Position', (W['d'], W['px'], W['tp']),
     ([[1, 1], [0, 1]], [[0, -1, -1]], [[0, 1, 0]]), 1e-12)
near('refreshdata: YDataSource evaluated again in the workspace', W['ly'], [[5, 5, 5]])

# ---- tick formats, ztickangle, polar axes ------------------------------------------------------------------------------
same('format_tick: patterns, commas, widths, %%', [format_tick(f, v) for f, v in (('$%,.2f', 1234567.891), ('%g°', 45), ('%d%%', 12.4), ('%+.1e', 1500), ('%,d', -1234567), ('%6.2f', 3.14159))],
     ['$1,234,567.89', '45°', '12%', '+1.5e+03', '-1,234,567', '  3.14'])
W, _ = run("""f = figure('Visible', 'off'); plot(1:3, [1000 2000 3000]); ytickformat('$%,.2f'); yf = ytickformat; yt = yticklabels; xtickformat('degrees'); xt = xticklabels;
xtickformat('auto'); xa = xtickformat; ytickformat('usd'); yu = ytickformat; ztickangle(45); za = ztickangle; ax = gca; close(f);""")
same('ytickformat and the labels written by it; named formats; auto', (text(W['yf']), text(W['yt'].a.reshape(-1)[0]), text(W['xt'].a.reshape(-1)[-1]), text(W['xa']), text(W['yu']), float(W['za'])),
     ('$%,.2f', '$1,000.00', '3°', '%g', '$%,.2f', 45.0))
W, _ = run("""f = figure('Visible', 'off'); polarplot(0:0.1:2*pi, 1 + (0:0.1:2*pi)); pax = gca; rt = rticks; rticks([0 2 4 6 8]); r2 = rticks; rticklabels({'a','b','c','d','e'}); rl = rticklabels;
thetaticks(0:45:315); tt = thetaticks; tl = thetaticklabels; rlim([0 10]); r3 = rlim; rlim('auto'); rm = pax.RLimMode; pax.ThetaDir = 'clockwise'; pax.ThetaZeroLocation = 'top';
td = pax.ThetaDir; ca = axes; hasr = any(strcmp(properties(ca), 'RTick')); hasp = any(strcmp(properties(pax), 'RTick'));""")
near('rticks auto and set, thetaticks, rlim set and auto', (W['rt'], W['r2'], W['tt'], W['r3']), ([[0, 2, 4, 6, 8]], [[0, 2, 4, 6, 8]], [np.arange(0, 360, 45.0)], [[0, 10]]))
same('labels set and the default degree labels; modes; direction; only polar axes list them',
     ([text(x) for x in W['rl'].a.reshape(-1)], text(W['tl'].a.reshape(-1)[1]), text(W['rm']), text(W['td']), bool(W['hasr']), bool(W['hasp'])),
     (['a', 'b', 'c', 'd', 'e'], '45°', 'auto', 'clockwise', False, True))
pax = W['pax']
sp = serialize_axes(pax)['polar']
same('the page is sent the polar settings', (sp['rtick'], sp['rticklabel'], sp['thetatick'][:2], sp['thetadir'], sp['thetazero']),
     ([0.0, 2.0, 4.0, 6.0, 8.0], ['a', 'b', 'c', 'd', 'e'], [0.0, 45.0], 'clockwise', 'top'))
raises("figure('Visible', 'off'); axes; rticks([1 2])", 'is for polar axes')
run("close all force")

# ---- graphs and trees -----------------------------------------------------------------------------------------------
W, _ = run("[X, Y] = gplot([0 1 1; 1 0 0; 1 0 0], [0 0; 1 0; 0 1]); [x, y, h, s] = treelayout([0 1 1 2 2]); f = figure('Visible', 'off'); treeplot([0 1 1 2 2]); lb = get(get(gca, 'XLabel'), 'String'); close(f);")
near('gplot: each edge once, NaN between', (W['X'], W['Y']), ([[0], [1], [np.nan], [0], [0], [np.nan]], [[0], [0], [np.nan], [0], [1], [np.nan]]))
near('treelayout: leaves across in walk order, parents over their children, depth down', (W['x'], W['y'], W['h'], W['s']),
     ([[2.25 / 4, 1.5 / 4, 3 / 4, 1 / 4, 2 / 4]], [[0.75, 0.5, 0.5, 0.25, 0.25]], 3, 1), 1e-12)
same('treeplot labels the height', text(W['lb']), 'height = 3')

# ---- colours ------------------------------------------------------------------------------------------------------------
W, _ = run("""c1 = validatecolor('red'); c2 = validatecolor({'#00F', 'g'}, 'multiple'); c3 = validatecolor(uint8([255 128 0]));
h1 = rgb2hex([1 0 0; 0 0.447 0.741]); h2 = rgb2hex([1 1 0], 'Shorthand', true); r1 = hex2rgb(["#FF0000"; "#00F"]); r2 = hex2rgb('ff8000');
m = gray(4); b1 = brighten(m, 0.5); b2 = brighten(m, -0.5);""")
near('validatecolor: names, codes and uint8 RGB as doubles', (W['c1'], W['c2'], W['c3']), ([[1, 0, 0]], [[0, 0, 1], [0, 1, 0]], [[1, 128 / 255, 0]]), 1e-12)
same('rgb2hex: codes for rows, shorthand', ([s for s in W['h1'].a.reshape(-1)], W['h2'].a.reshape(-1)[0]), (['#FF0000', '#0072BD'], '#FF0'))
near('hex2rgb; brighten raises to 1 - beta, or 1/(1 + beta)', (W['r1'], W['r2'], W['b1'], W['b2']),
     ([[1, 0, 0], [0, 0, 1]], [[1, 128 / 255, 0]], np.linspace(0, 1, 4)[:, None].repeat(3, 1) ** 0.5, np.linspace(0, 1, 4)[:, None].repeat(3, 1) ** 2), 1e-12)
raises("validatecolor({'r', 'g'})", 'Specify one color only.')
raises("hex2rgb('#GG0000')", 'is not a hex colour code')

# ---- 3-D helpers ----------------------------------------------------------------------------------------------------------
W, _ = run("""[Nx, Ny, Nz] = surfnorm(peaks(5)); un = max(abs(Nx(:).^2 + Ny(:).^2 + Nz(:).^2 - 1)); [a1, a2, a3] = surfnorm(meshgrid(1:3), meshgrid(1:3)', zeros(3));
[X, Y] = meshgrid(-1:0.5:1); Z = X + 2*Y; [b1, b2, b3] = surfnorm(X, Y, Z);
fv.faces = [1 2 3]; fv.vertices = [0 0 0; 3 0 0; 0 3 0]; nfv = shrinkfaces(fv, 0.25); [nf, nv] = shrinkfaces([1 2 3], [0 0 0; 3 0 0; 0 3 0], 0.25);
[x3, y3, z3] = meshgrid(1:3); Cv = x3 + 10*y3 + 100*z3; nc = isocolors(x3, y3, z3, Cv, [1.5 2 2; 3 1 1]);
f = figure('Visible', 'off'); surf(peaks(10)); hl = lightangle(45, 30); [az, el] = lightangle(hl); lp = hl.Position; close(f);""")
near('surfnorm: unit normals, up for a flat surface, (-1, -2, 1)/sqrt(6) for z = x + 2y', (W['un'], [W['a1'][1, 1], W['a2'][1, 1], W['a3'][1, 1]],
     [W['b1'][2, 2], W['b2'][2, 2], W['b3'][2, 2]]), (0, [0, 0, 1], np.array([-1, -2, 1]) / math.sqrt(6)), 1e-12)
near('shrinkfaces: towards the centroid by sqrt(sf), as a struct or two outputs', (W['nfv'].get1('vertices'), W['nv'], W['nf']),
     ([[0.5, 0.5, 0], [2, 0.5, 0], [0.5, 2, 0]], [[0.5, 0.5, 0], [2, 0.5, 0], [0.5, 2, 0]], [[1, 2, 3]]))
near('isocolors: linear in the volume', W['nc'], [[221.5], [113]])
near('lightangle: there and back, the light where view puts the camera', (W['az'], W['el'], W['lp']),
     (45, 30, [[math.sin(math.radians(45)) * math.cos(math.radians(30)), -math.cos(math.radians(45)) * math.cos(math.radians(30)), 0.5]]), 1e-12)

sys.exit(C.done())
