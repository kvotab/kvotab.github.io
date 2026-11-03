"""World data for the names programs use for it: coastlines (load
coastlines: coastlat and coastlon), landareas, worldlakes, worldrivers and
worldcities (shaperead, shapeinfo, geoshow, mapshow).

They are Natural Earth's (public domain), fetched from jsDelivr's copy of
its repository when a program first asks for one of these names and no file
of that name is found, and kept for the session. Nothing is fetched before.
"""
import json
import math

import numpy as np

from .values import MError

BASE = 'https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@v5.1.2/geojson/'
SETS = {
    'coastlines': 'ne_110m_coastline',
    'landareas': 'ne_50m_land',
    'worldlakes': 'ne_50m_lakes',
    'worldrivers': 'ne_50m_rivers_lake_centerlines',
    'worldcities': 'ne_110m_populated_places_simple',
}
FETCH = None          # tests: async (url) -> text, in place of the network
_CACHE = {}


def dataset(fname, kind):
    """The data set a file name names, or None: kind 'mat' for load
    (coastlines, coastlines.mat), 'shp' for the shapefile readers
    (landareas, landareas.shp)."""
    if not isinstance(fname, str) or '/' in fname or '\\' in fname:
        return None
    name = fname.strip().lower()
    for ext in (('.mat',) if kind == 'mat' else ('.shp', '.dbf', '.shx')):
        if name.endswith(ext):
            name = name[:-len(ext)]
    if name not in SETS or (name == 'coastlines') != (kind == 'mat'):
        return None
    return name


async def _text(url):
    if FETCH is not None:
        return await FETCH(url)
    try:
        from pyodide.http import pyfetch
    except ImportError:
        raise MError('map:data:noNetwork', f'The world data cannot be fetched here ({url}).')
    try:
        r = await pyfetch(url)
    except Exception as e:
        raise MError('map:data:fetchFailed', f'The world data could not be fetched from {url} ({e}).')
    if not r.ok:
        raise MError('map:data:fetchFailed', f'The world data could not be fetched from {url} (HTTP {r.status}).')
    return await r.string()


async def features(name):
    """The GeoJSON features of a data set (fetched once)."""
    if name not in _CACHE:
        doc = json.loads(await _text(BASE + SETS[name] + '.geojson'))
        _CACHE[name] = [f for f in doc.get('features', []) if f.get('geometry') and f['geometry'].get('coordinates')]
    return _CACHE[name]


async def coastlines():
    """coastlat and coastlon: column vectors, the lines parted by NaN."""
    lat, lon = [], []
    for f in await features('coastlines'):
        g = f['geometry']
        lines = [g['coordinates']] if g['type'] == 'LineString' else g['coordinates']
        for ln in lines:
            if not ln:
                continue
            lon += [p[0] for p in ln] + [math.nan]
            lat += [p[1] for p in ln] + [math.nan]
    return np.array(lat).reshape(-1, 1), np.array(lon).reshape(-1, 1)


def _signed_area(ring):
    x, y = ring[:, 0], ring[:, 1]
    return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


def _record(g):
    """A GeoJSON geometry as shaperead's record: (shape type, bounding box, x, y),
    parts parted by NaN; polygons' outer rings clockwise and holes anticlockwise."""
    t, c = g['type'], g['coordinates']
    if t == 'Point':
        x, y = float(c[0]), float(c[1])
        return 1, (x, y, x, y), np.array([x]), np.array([y])
    if t == 'MultiPoint':
        p = np.array(c, float)[:, :2]
        return 8, (p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()), p[:, 0].copy(), p[:, 1].copy()
    if t in ('LineString', 'MultiLineString'):
        parts = [np.array(ln, float)[:, :2] for ln in ([c] if t == 'LineString' else c) if ln]
        stype = 3
    elif t in ('Polygon', 'MultiPolygon'):
        parts = []
        for poly in ([c] if t == 'Polygon' else c):
            for k, ring in enumerate(poly):
                if not ring:
                    continue
                r = np.array(ring, float)[:, :2]
                if (_signed_area(r) > 0) == (k == 0):      # outer anticlockwise, or a hole clockwise
                    r = r[::-1]
                parts.append(r)
        stype = 5
    else:
        return 0, None, np.zeros(0), np.zeros(0)
    if not parts:
        return 0, None, np.zeros(0), np.zeros(0)
    xs = np.concatenate([np.append(p[:, 0], np.nan) for p in parts])
    ys = np.concatenate([np.append(p[:, 1], np.nan) for p in parts])
    return stype, (np.nanmin(xs), np.nanmin(ys), np.nanmax(xs), np.nanmax(ys)), xs, ys


async def shapes(name):
    """A data set as shaperead reads a shapefile: (shape type, bounding box,
    records, attribute names, their dBASE types, rows of values). Its one
    attribute is Name, where Natural Earth names the features."""
    fs = await features(name)
    recs = [_record(f['geometry']) for f in fs]
    stype = next((r[0] for r in recs if r[0]), 0)
    boxes = np.array([r[1] for r in recs if r[1] is not None], float).reshape(-1, 4)
    bbox = (boxes[:, 0].min(), boxes[:, 1].min(), boxes[:, 2].max(), boxes[:, 3].max()) if len(boxes) else (0.0, 0.0, 0.0, 0.0)
    if any('name' in f.get('properties', {}) for f in fs):
        names, types = ['Name'], ['C']
        rows = [[str(f.get('properties', {}).get('name') or '')] for f in fs]
    else:
        names, types, rows = [], [], [[] for _ in fs]
    return stype, bbox, recs, names, types, rows
