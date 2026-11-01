"""Colormaps: m-by-3 arrays of RGB values in 0..1.

The ramps (jet, hot, gray and the rest) follow their usual definitions;
the default map is a blue-to-yellow ramp through anchor colours chosen
for this page.
"""
import numpy as np

from .values import MError, Char, Str, py_str

F64 = np.float64

_ANCHORS = {
    'parula': [(0.208, 0.166, 0.529), (0.153, 0.385, 0.890), (0.047, 0.584, 0.863), (0.110, 0.700, 0.700),
               (0.420, 0.780, 0.420), (0.800, 0.740, 0.240), (0.990, 0.800, 0.200), (0.976, 0.984, 0.055)],
    'viridis': [(0.267, 0.005, 0.329), (0.283, 0.141, 0.458), (0.254, 0.265, 0.530), (0.207, 0.372, 0.553),
                (0.164, 0.471, 0.558), (0.128, 0.567, 0.551), (0.135, 0.659, 0.518), (0.267, 0.749, 0.441),
                (0.478, 0.821, 0.318), (0.741, 0.873, 0.150), (0.993, 0.906, 0.144)],
    'turbo': [(0.190, 0.072, 0.232), (0.275, 0.378, 0.835), (0.163, 0.666, 0.975), (0.106, 0.898, 0.712),
              (0.483, 0.996, 0.302), (0.817, 0.900, 0.207), (0.989, 0.646, 0.214), (0.910, 0.305, 0.050),
              (0.635, 0.100, 0.015), (0.480, 0.016, 0.011)],
    'jet': None,
}


def _interp(anchors, m, positions=None):
    a = np.asarray(anchors, F64)
    n = a.shape[0]
    pos = np.linspace(0, 1, n) if positions is None else np.asarray(positions, F64)
    t = np.linspace(0, 1, m) if m > 1 else np.array([0.0])
    return np.column_stack([np.interp(t, pos, a[:, k]) for k in range(3)])


def colormap_by_name(name, m=256):
    name = name.lower()
    m = int(m)
    if m <= 0:
        return np.zeros((0, 3))
    r = np.linspace(0, 1, m) if m > 1 else np.array([0.0])
    if name in ('parula', 'viridis', 'turbo'):
        return _interp(_ANCHORS[name], m)
    if name == 'jet':
        return _interp([(0, 0, 0.5), (0, 0, 1), (0, 1, 1), (1, 1, 0), (1, 0, 0), (0.5, 0, 0)], m,
                       [0, 1 / 8, 3 / 8, 5 / 8, 7 / 8, 1])
    if name == 'gray':
        return np.column_stack([r, r, r])
    if name == 'hot':
        n1 = 3 / 8
        n2 = 6 / 8
        red = np.clip(r / n1, 0, 1)
        green = np.clip((r - n1) / (n2 - n1), 0, 1)
        blue = np.clip((r - n2) / (1 - n2), 0, 1)
        return np.column_stack([red, green, blue])
    if name == 'cool':
        return np.column_stack([r, 1 - r, np.ones(m)])
    if name == 'spring':
        return np.column_stack([np.ones(m), r, 1 - r])
    if name == 'summer':
        return np.column_stack([r, 0.5 + r / 2, 0.4 * np.ones(m)])
    if name == 'autumn':
        return np.column_stack([np.ones(m), r, np.zeros(m)])
    if name == 'winter':
        return np.column_stack([np.zeros(m), r, 0.5 + (1 - r) / 2])
    if name == 'bone':
        g = np.column_stack([r, r, r])
        h = colormap_by_name('hot', m)[:, ::-1]
        return (7 * g + h) / 8
    if name == 'copper':
        return np.minimum(1, np.column_stack([r * 1.25, r * 0.7812, r * 0.4975]))
    if name == 'pink':
        g = np.column_stack([r, r, r])
        return np.sqrt((2 * g + colormap_by_name('hot', m)) / 3)
    if name == 'hsv':
        import colorsys
        return np.array([colorsys.hsv_to_rgb(h, 1, 1) for h in (np.arange(m) / m)])
    if name == 'lines':
        from .graphics_base import COLOR_ORDER
        return np.array([COLOR_ORDER[i % len(COLOR_ORDER)] for i in range(m)])
    if name == 'prism':
        base = [(1, 0, 0), (1, 0.5, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (2 / 3, 0, 1)]
        return np.array([base[i % 6] for i in range(m)], F64)
    if name == 'flag':
        base = [(1, 0, 0), (1, 1, 1), (0, 0, 1), (0, 0, 0)]
        return np.array([base[i % 4] for i in range(m)], F64)
    if name == 'white':
        return np.ones((m, 3))
    if name == 'colorcube':
        k = max(2, int(round(m ** (1 / 3))))
        v = np.linspace(0, 1, k)
        cube = np.array([(a, b, c) for a in v for b in v for c in v])
        return cube[:m] if cube.shape[0] >= m else np.vstack([cube, np.ones((m - cube.shape[0], 3))])
    raise MError('MATLAB:colormap:InvalidName', f"Unrecognized colormap '{name}'.")


NAMES = ['parula', 'viridis', 'turbo', 'jet', 'gray', 'hot', 'cool', 'spring', 'summer', 'autumn', 'winter', 'bone',
         'copper', 'pink', 'hsv', 'lines', 'prism', 'flag', 'white', 'colorcube']


def as_colormap(v):
    t = type(v)
    if t in (Char, Str):
        return colormap_by_name(py_str(v), 256)
    a = np.asarray(v, F64)
    if a.ndim != 2 or a.shape[1] != 3:
        raise MError('MATLAB:colormap:InvalidInputType', 'Colormap must be an m-by-3 array of values between 0 and 1.')
    if a.size and (a.min() < 0 or a.max() > 1):
        raise MError('MATLAB:colormap:InvalidInputRange', 'Colormap values must be between 0 and 1.')
    return a
