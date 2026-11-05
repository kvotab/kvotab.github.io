"""The mapping functions, run natively (CPython with numpy and scipy; Pillow
for the GeoTIFF checks): geodesy against Vincenty's published example and
closed forms, ECEF and local frames, projections against Snyder's worked
examples and UTM's known values, polygons, map axes (projection, frame,
graticule, breaks at the map's edge), geographic axes, shapefiles (one
built byte by byte here, from the format's description, and round trips)
and GeoTIFF rasters.

    python3 test_map.py          (from any folder)
"""
import asyncio
import math
import os
import struct
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char, Cell, Struct  # noqa: E402
from plab.graphics_base import serialize_figure  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-map-')


def run(code):
    R.BASE.clear()
    R.BASE.gnames.clear()
    R.take_output()
    asyncio.run(R.execute(f"cd('{TMP}');\n" + code))
    return R.BASE, R.take_output()


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


def v(x):
    if isinstance(x, (bool, float, int)):
        return np.array([float(x)])
    return np.asarray(x, float).reshape(-1)


def near(label, got, want, tol=1e-9):
    g = np.concatenate([v(x) for x in got]) if isinstance(got, tuple) else v(got)
    w = np.asarray(want, float).reshape(-1)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol)
    return C(label, ok, f'got {g.tolist()}, want {w.tolist()}')


def same(label, got, want):
    return C(label, got == want, f'got {got!r}, want {want!r}')


def text(x):
    return x.str() if isinstance(x, Char) else x


# ---- units ---------------------------------------------------------------------------------------------------------
W, _ = run("a = deg2km(1); b = km2deg(6371*pi/180); c = deg2nm(1); d = nm2km(1); e = deg2km(1, 'moon'); f = unitsratio('km', 'mile'); g = sm2km(1);")
near('deg2km and its kin', (W['a'], W['b'], W['c'], W['d'], W['e'], W['f'], W['g']),
     [6371 * math.pi / 180, 1, 6371 * math.pi / 180 / 1.852, 1.852, 1737.4 * math.pi / 180, 1.609344, 1.609344])
W, _ = run("a = wrapTo180([190 -190 180 -180 540 0]); b = wrapTo360([-10 0 360 720 370]); c = wrapToPi(3*pi/2); d = wrapTo2Pi(-pi/2);")
near('wrapTo180, wrapTo360, wrapToPi, wrapTo2Pi', (W['a'], W['b'], W['c'], W['d']), [-170, 170, 180, -180, 180, 0, 350, 0, 360, 360, 10, -math.pi / 2, 3 * math.pi / 2])
W, _ = run("a = degrees2dms(-12.5125); b = dms2degrees([-12 30 45; 0 -30 0]); c = degrees2dm(10.75); d = dm2degrees([10 45]);")
near('degrees, minutes and seconds', (W['a'], W['b'], W['c'], W['d']), [-12, 30, 45, -12.5125, -0.5, 10, 45, 10.75], 1e-9)

# ---- ellipsoids ------------------------------------------------------------------------------------------------------
W, _ = run("e = wgs84Ellipsoid; a = e.SemimajorAxis; b = e.SemiminorAxis; f = e.InverseFlattening; k = referenceEllipsoid('grs80', 'kilometer'); ka = k.SemimajorAxis; c = e.Code; s = referenceSphere('earth'); r = s.Radius;")
near('WGS 84: a, b, 1/f; GRS 80 in km; the Earth sphere', (W['a'], W['b'], W['f'], W['ka'], W['c'], W['r']),
     [6378137, 6356752.314245179, 298.257223563, 6378.137, 7030, 6371000], 1e-9)
W, _ = run("e = referenceEllipsoid('bessel'); n = e.Name; e.LengthUnit = 'kilometer'; a = e.SemimajorAxis;")
same('a named ellipsoid, its unit changed', (text(W['n']), round(W['a'], 6)), ('Bessel 1841', 6377.397155))

# ---- geodesy ------------------------------------------------------------------------------------------------------------
lat1, lon1, lat2, lon2 = 59.33, 18.07, 57.71, 11.97
p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
hav = 2 * math.asin(math.sqrt(math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))
az = math.degrees(math.atan2(math.sin(dl) * math.cos(p2), math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360
W, _ = run(f"[d, a] = distance({lat1}, {lon1}, {lat2}, {lon2}); b = azimuth({lat1}, {lon1}, {lat2}, {lon2});")
near('distance and azimuth on the sphere (haversine)', (W['d'], W['a'], W['b']), [math.degrees(hav), az, az], 1e-12)
# Vincenty's example: Flinders Peak to Buninyong on GRS 80
fp = (-(37 + 57 / 60 + 3.7203 / 3600), 144 + 25 / 60 + 29.5244 / 3600)
bu = (-(37 + 39 / 60 + 10.1561 / 3600), 143 + 55 / 60 + 35.3839 / 3600)
W, _ = run(f"e = referenceEllipsoid('grs80'); [s, a] = distance({fp[0]!r}, {fp[1]!r}, {bu[0]!r}, {bu[1]!r}, e); [la, lo] = reckon({fp[0]!r}, {fp[1]!r}, s, a, e);")
near("Vincenty's example on GRS 80: 54972.271 m at 306 deg 52' 05.37''", (W['s'], W['a']), [54972.271, 306 + 52 / 60 + 5.37 / 3600], 2e-8)
near('reckon goes back to the far point', (W['la'], W['lo']), [bu[0], bu[1]], 1e-10)
W, _ = run("[la, lo] = reckon(0, 0, 90, 90); [la2, lo2] = reckon(0, 170, 20, 90); d = distance('rh', 0, 0, 0, 90);")
near('reckon along the equator; across the date line; a rhumb line along it', (W['la'], W['lo'], W['la2'], W['lo2'], W['d']), [0, 90, 0, -170, 90], 1e-12)
W, _ = run("[lat, lon] = track2(0, 0, 0, 90); n = numel(lat); m = lat(50);")
near('track2: 100 points, along the equator', (W['n'], W['m']), [100, 0], 1e-12)
W, _ = run("a = areaint([0 0 90 0], [0 90 0 0]); b = areaquad(0, 0, 90, 90); c = areaquad(-90, -180, 90, 180); e = wgs84Ellipsoid; d = areaquad(-90, -180, 90, 180, e); s = e.SurfaceArea;")
near('areaint of an octant, areaquad of the octant and the sphere; the ellipsoid surface', (W['a'], W['b'], W['c'], W['d'] / W['s']), [0.125, 0.125, 1, 1], 1e-12)
W, _ = run("m = meridianarc(0, pi/2, wgs84Ellipsoid);")
near('the quarter meridian of WGS 84', W['m'], 10001965.729, 1e-9)

# ---- ECEF and local frames ------------------------------------------------------------------------------------------------
W, _ = run("e = wgs84Ellipsoid; [x, y, z] = geodetic2ecef(e, 0, 0, 0); [x2, y2, z2] = geodetic2ecef(e, 90, 0, 0); [x3, y3, z3] = geodetic2ecef(e, 0, 90, 100);")
near('geodetic2ecef: the equator, the pole, 100 m up at 90 E', (W['x'], W['y'], W['z'], W['x2'], W['z2'], W['y3']),
     [6378137, 0, 0, 0, 6356752.314245179, 6378237], 1e-9)
rng = np.random.default_rng(5)
pts = np.column_stack([rng.uniform(-89, 89, 20), rng.uniform(-180, 180, 20), rng.uniform(-1000, 9000, 20)])
W, _ = run("e = wgs84Ellipsoid; P = " + str(pts.tolist()).replace('], [', '; ').replace('[[', '[').replace(']]', ']') +
           "; [x, y, z] = geodetic2ecef(e, P(:,1), P(:,2), P(:,3)); [la, lo, h] = ecef2geodetic(e, x, y, z);")
near('ecef2geodetic undoes geodetic2ecef', (W['la'], W['lo'], W['h']), np.concatenate([pts[:, 0], pts[:, 1], pts[:, 2]]), 1e-8)
W, _ = run("[e1, n1, u1] = geodetic2enu(59.33, 18.07, 1030, 59.33, 18.07, 30, wgs84Ellipsoid); [az, el, r] = enu2aer(1, 1, 0);"
           "[nn, ee, dd] = geodetic2ned(59.33, 18.07, 1030, 59.33, 18.07, 30, wgs84Ellipsoid);")
near('a point straight up is up; enu2aer of (1, 1, 0); NED has down negative', (W['e1'], W['n1'], W['u1'], W['az'], W['el'], W['r'], W['dd']),
     [0, 0, 1000, 45, 0, math.sqrt(2), -1000], 1e-6)
W, _ = run("[a, b, c] = geodetic2aer(59.4, 18.2, 10, 59.33, 18.07, 30, wgs84Ellipsoid); [la, lo, h] = aer2geodetic(a, b, c, 59.33, 18.07, 30, wgs84Ellipsoid);")
near('aer2geodetic undoes geodetic2aer', (W['la'], W['lo'], W['h']), [59.4, 18.2, 10], 1e-8)

# ---- projections --------------------------------------------------------------------------------------------------------------
W, _ = run("p = projcrs(32631); [x, y] = projfwd(p, 0, 0); [x2, y2] = projfwd(p, 0, 3); n = p.Name;")
near('UTM zone 31N at the equator: 166021.443 m 3 degrees west of its meridian, 500000 on it', (W['x'], W['y'], W['x2'], W['y2']), [166021.4431, 0, 500000, 0], 1e-9)
same('the name of an EPSG code', text(W['n']), 'WGS 84 / UTM zone 31N')
e66 = 0.0822718542230039
W, _ = run(f"m = defaultm('eqaconic'); m.geoid = [6378206.4 {e66!r}]; m.mapparallels = [29.5 45.5]; m.origin = [23 -96 0]; [x, y] = projfwd(m, 35, -75);"
           f"l = defaultm('lambert'); l.geoid = [6378206.4 {e66!r}]; l.mapparallels = [33 45]; l.origin = [23 -96 0]; [x2, y2] = projfwd(l, 35, -75);")
near("Snyder's examples on Clarke 1866: Albers and Lambert conformal conic", (W['x'], W['y'], W['x2'], W['y2']), [1885472.7, 1535925.0, 1894410.9, 1564649.5], 1e-7)
for code in (3006, 3021, 3035, 3034, 2154, 27700, 5070, 3857, 3395, 32661, 3008):
    W, _ = run(f"p = projcrs({code}); [x, y] = projfwd(p, [{60 if code not in (32661,) else 85} 61], [15 16]); [la, lo] = projinv(p, x, y);")
    near(f'EPSG {code}: projinv undoes projfwd', (W['la'], W['lo']), [60 if code != 32661 else 85, 61, 15, 16], 1e-9)
W, _ = run("p = projcrs(3857); [x, y] = projfwd(p, 45, 90);")
near('Pseudo-Mercator: R*lon and R*log(tan(pi/4 + lat/2))', (W['x'], W['y']), [6378137 * math.pi / 2, 6378137 * math.log(math.tan(math.pi / 4 + math.pi / 8))], 1e-12)

# ---- polygons ------------------------------------------------------------------------------------------------------------------
W, _ = run("xv = [0 4 4 0 0 NaN 1 2 2 1 1]; yv = [0 0 4 4 0 NaN 1 1 2 2 1]; [in, on] = inpolygon([0.5 1.5 3 5 4 2], [0.5 1.5 3 5 2 1.5], xv, yv);")
same('inpolygon: inside, in the hole, inside, outside, on the edge, on the hole edge', ([bool(x) for x in v(W['in'])], [bool(x) for x in v(W['on'])]),
     ([True, False, True, False, True, True], [False, False, False, False, True, True]))
W, _ = run("a = polyarea([0 4 4 0], [0 0 3 3]); b = polyarea([0 1 0], [0 0 1]); c = ispolycw([0 0 1 1], [0 1 1 0]); [x, y] = poly2ccw([0 0 1 1], [0 1 1 0]); d = ispolycw(x, y);")
same('polyarea, ispolycw, poly2ccw', (W['a'], W['b'], W['c'], W['d']), (12.0, 0.5, True, False))
W, _ = run("[xi, yi] = polyxpoly([0 2], [0 2], [0 2], [2 0]); [xc, yc] = polysplit([1 2 NaN 3 4], [5 6 NaN 7 8]); n = numel(xc); [x, y] = polyjoin(xc, yc);")
same('polyxpoly, polysplit, polyjoin', (W['xi'], W['yi'], W['n'], [None if math.isnan(t) else t for t in v(W['x'])]), (1.0, 1.0, 2.0, [1.0, 2.0, None, 3.0, 4.0]))

# ---- map axes -------------------------------------------------------------------------------------------------------------------
W, _ = run("close all force; axesm('mercator', 'Frame', 'on', 'Grid', 'on'); h = plotm([10 20], [30 40]); x = get(h, 'XData'); y = get(h, 'YData'); m = gcm; [xp, yp] = projfwd(m, [10 20], [30 40]); t = ismap; tags = unique(get(get(gca, 'Children'), 'Tag')); vis = get(gca, 'Visible');")
near('plotm draws what projfwd of the map gives', (W['x'], W['y']), np.concatenate([v(W['xp']), v(W['yp'])]), 1e-12)
same('map axes: a map, hidden axis, frame and graticule', (W['t'], text(W['vis']), sorted(x.str() for x in W['tags'].a.reshape(-1))), (True, 'off', ['', 'Frame', 'Graticule']))
W, _ = run("close all force; axesm('eqdcylin'); h = plotm([0 0 0], [170 -170 -160]); x = get(h, 'XData');")
same('a line across the map edge is broken there', [math.isnan(t) for t in v(W['x'])], [False, True, False, False])
W, _ = run("close all force; axesm('ortho', 'Origin', [0 0 0]); h = plotm([0 0], [10 120]); x = get(h, 'XData');")
same('an orthographic map leaves the far side out', [math.isnan(t) for t in v(W['x'])], [False, True])
for region, proj in (('World', 'robinson'), ('Europe', 'eqdconic'), ('Arctic', 'stereo')):
    W, _ = run(f"close all force; worldmap('{region}'); m = gcm; p = m.mapprojection;")
    same(f"worldmap('{region}') chooses {proj}", text(W['p']), proj)
W, _ = run("close all force; worldmap([55 70], [10 25]); n = numel(findobj(gca, 'Tag', 'MLabel')); k = numel(findobj(gca, 'Tag', 'PLabel'));")
C('worldmap labels meridians and parallels', W['n'] >= 2 and W['k'] >= 2, str((W['n'], W['k'])))
W, _ = run("close all force; axesm('eqdcylin'); setm(gca, 'MapLatLimit', [0 60], 'Grid', 'on'); m = gcm; l = m.maplatlimit; yl = ylim;")
near('setm changes the limits, and the axes take the frame with a margin of 2%', (W['l'], W['yl']), [0, 60, -0.02 * math.radians(60), 1.02 * math.radians(60)], 1e-12)
raises = lambda code, words: C(f'refused: {code}', words in (lambda W: text(W['e']))(run(f"try, {code}; e = ''; catch ex, e = ex.message; end")[0]), '')
raises("close all force; plot(1:3); plotm(1, 2)", 'not a map axes')
raises("axesm('nosuch')", 'not a projection')

# ---- geographic axes -------------------------------------------------------------------------------------------------------------
W, _ = run("close all force; geoplot([59.3 57.7], [18.1 12.0], 'b-o'); geolimits([55 65], [10 25]); k = class(gca); t = get(gca, 'Type'); d = get(gca, 'DataAspectRatio'); [la, lo] = geolimits; f = gcf;")
same('geoplot makes geographic axes', (text(W['k']), text(W['t'])), ('matlab.graphics.axis.GeographicAxes', 'geoaxes'))
near('their aspect is the middle latitude\'s; geolimits', (W['d'][0, :2], W['la'], W['lo']), [1, math.cos(math.radians(60)), 55, 65, 10, 25], 1e-12)
same('the page is told to label their ticks in degrees', serialize_figure(W['f'])['axes'][0]['geo'], True)

# ---- shapefiles --------------------------------------------------------------------------------------------------------------------
# a shapefile of two polylines, the second of two parts, with a .dbf of a number and a name, made from the layout itself


def write_test_shapefile(root):
    recs = []
    parts = [[[(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]], [[(5.0, 5.0), (6.0, 5.0)], [(7.0, 7.0), (8.0, 8.0), (9.0, 7.0)]]]
    for k, prt in enumerate(parts):
        pts = [p for part in prt for p in part]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        starts, s = [], 0
        for part in prt:
            starts.append(s)
            s += len(part)
        body = struct.pack('<i4d2i', 3, min(xs), min(ys), max(xs), max(ys), len(prt), len(pts)) + struct.pack(f'<{len(prt)}i', *starts) + \
            b''.join(struct.pack('<2d', *p) for p in pts)
        recs.append(struct.pack('>2i', k + 1, len(body) // 2) + body)
    data = b''.join(recs)
    head = struct.pack('>7i', 9994, 0, 0, 0, 0, 0, (100 + len(data)) // 2) + struct.pack('<2i', 1000, 3) + struct.pack('<8d', 0, 0, 9, 8, 0, 0, 0, 0)
    with open(root + '.shp', 'wb') as fh:
        fh.write(head + data)
    fields = [(b'DEPTH', b'N', 8, 2), (b'NAME', b'C', 10, 0)]
    rows = [(' 12.50', 'river'), ('  3.25', 'canal')]
    hdr = struct.pack('<4BIHH20x', 3, 126, 1, 1, len(rows), 32 + 32 * len(fields) + 1, 1 + 8 + 10)
    for name, t, ln, dec in fields:
        hdr += name.ljust(11, b'\x00') + t + b'\x00' * 4 + bytes([ln, dec]) + b'\x00' * 14
    hdr += b'\r'
    body = b''.join(b' ' + a.rjust(8).encode() + b.ljust(10).encode() for a, b in rows)
    with open(root + '.dbf', 'wb') as fh:
        fh.write(hdr + body + b'\x1a')


write_test_shapefile(os.path.join(TMP, 'lines'))
W, _ = run("S = shaperead('lines'); n = numel(S); g = S(2).Geometry; x = S(2).X; d = [S.DEPTH]; nm = S(1).NAME; info = shapeinfo('lines.shp'); st = info.ShapeType; bb = S(1).BoundingBox;")
same('shaperead of a file made from the layout: features, geometry, attributes', (W['n'], text(W['g']), v(W['d']).tolist(), text(W['nm']), text(W['st'])),
     (2.0, 'Line', [12.5, 3.25], 'river', 'PolyLine'))
same('its parts end in NaN', [None if math.isnan(t) else t for t in v(W['x'])], [5.0, 6.0, None, 7.0, 8.0, 9.0, None])
near('and the bounding box', W['bb'], [0, 0, 2, 1])
W, _ = run("S = struct('Geometry', {'Point', 'Point'}, 'X', {1.5, -2}, 'Y', {2.5, 4}, 'Label', {'a', 'bb'}, 'Count', {3, 4}); shapewrite(S, 'pts.shp'); T = shaperead('pts'); x = [T.X]; c = [T.Count]; l = T(2).Label;"
           "U = shaperead('pts', 'UseGeoCoords', true); f = isfield(U, 'Lat'); V = shaperead('pts', 'Selector', {@(c) c > 3, 'Count'}); nv = numel(V);")
same('shapewrite then shaperead: points and attributes; UseGeoCoords; Selector', (v(W['x']).tolist(), v(W['c']).tolist(), text(W['l']), W['f'], W['nv']),
     ([1.5, -2.0], [3.0, 4.0], 'bb', True, 1.0))
with open(os.path.join(TMP, 'bad.shp'), 'wb') as fh:
    fh.write(b'\x00' * 50)
raises("shaperead('bad.shp')", 'is not a shapefile')

# ---- world data (geodata.py) -----------------------------------------------------------------------------------------------------
# The network is replaced by small made-up GeoJSON, in the layout of the files
# fetched; what is asked for is counted.
import json  # noqa: E402
from plab import geodata as GD  # noqa: E402

FAKE = {
    'ne_110m_coastline': {'features': [
        {'properties': {}, 'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [1, 1], [2, 0]]}},
        {'properties': {}, 'geometry': {'type': 'LineString', 'coordinates': [[10, 50], [11, 51]]}},
        {'properties': {}, 'geometry': None}]},
    'ne_50m_land': {'features': [
        # an island, its outer ring anticlockwise and its hole clockwise (both the wrong way for a shapefile)
        {'properties': {'featurecla': 'Land'}, 'geometry': {'type': 'Polygon', 'coordinates': [
            [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [1, 2], [2, 2], [2, 1], [1, 1]]]}},
        {'properties': {'featurecla': 'Land'}, 'geometry': {'type': 'MultiPolygon', 'coordinates': [
            [[[10, 10], [10, 11], [11, 11], [11, 10], [10, 10]]], [[[20, 20], [20, 21], [21, 21], [21, 20], [20, 20]]]]}}]},
    'ne_50m_lakes': {'features': [
        {'properties': {'name': 'Long Lake'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[5, 5], [5, 6], [6, 6], [6, 5], [5, 5]]]}},
        {'properties': {'name': None}, 'geometry': {'type': 'Polygon', 'coordinates': [[[7, 7], [7, 8], [8, 8], [8, 7], [7, 7]]]}}]},
    'ne_110m_populated_places_simple': {'features': [
        {'properties': {'name': 'Townsend'}, 'geometry': {'type': 'Point', 'coordinates': [12.5, 55.5]}},
        {'properties': {'name': 'Riverby'}, 'geometry': {'type': 'Point', 'coordinates': [-3.25, 40.75]}}]},
}
ASKED = []


async def fake_fetch(url):
    ASKED.append(url)
    name = url.rsplit('/', 1)[-1].replace('.geojson', '')
    return json.dumps(FAKE[name])


GD.FETCH = fake_fetch
GD._CACHE.clear()
same('nothing is fetched until a program asks for world data', ASKED, [])
W, _ = run("load coastlines; s = size(coastlat); n = nnz(isnan(coastlon)); a = coastlat(1:4)'; b = coastlon(5:6)'; S = load('coastlines'); f = sort(fieldnames(S))'; load coastlines coastlat; ")
same('load coastlines: coastlat and coastlon, column vectors, each line ended by NaN', (v(W['s']).tolist(), W['n'], v(W['b']).tolist(), [x.str() for x in W['f'].a.reshape(-1)]),
     ([7.0, 1.0], 2.0, [10.0, 11.0], ['coastlat', 'coastlon']))
same('fetched once, from Natural Earth on jsDelivr', ASKED, [GD.BASE + 'ne_110m_coastline.geojson'])
C('the URL names a version of the Natural Earth repository', '/natural-earth-vector@v' in GD.BASE, GD.BASE)
W, _ = run("S = shaperead('landareas', 'UseGeoCoords', true); n = numel(S); g = S(1).Geometry; lo = S(1).Lon; la = S(1).Lat; f = fieldnames(S)'; bb = S(2).BoundingBox;"
           "k = find(isnan(lo)); cw1 = ispolycw(lo(1:k(1)-1), la(1:k(1)-1)); cw2 = ispolycw(lo(k(1)+1:k(2)-1), la(k(1)+1:k(2)-1));")
same('shaperead landareas: polygons, Lon and Lat, no attributes', (W['n'], text(W['g']), [x.str() for x in W['f'].a.reshape(-1)]),
     (2.0, 'Polygon', ['Geometry', 'BoundingBox', 'Lon', 'Lat']))
same("its outer ring clockwise and its hole anticlockwise, as in a shapefile", (W['cw1'], W['cw2']), (True, False))
near('a multipolygon is one feature, its parts ended by NaN; its bounding box', W['bb'], [10, 10, 21, 21])
W, _ = run("T = shaperead('worldcities.shp'); x = [T.X]; y = [T.Y]; nm = T(1).Name; g = T(2).Geometry; L = shaperead('worldlakes'); e = L(2).Name;"
           "info = shapeinfo('worldlakes.shp'); nf = info.NumFeatures; at = info.Attributes(1).Name; st = info.ShapeType;")
same('worldcities: points named; worldlakes: a lake with no name has an empty Name', (v(W['x']).tolist(), v(W['y']).tolist(), text(W['nm']), text(W['g']), text(W['e'])),
     ([12.5, -3.25], [55.5, 40.75], 'Townsend', 'Point', ''))
same('shapeinfo of a data set', (W['nf'], text(W['at']), text(W['st'])), (2.0, 'Name', 'Polygon'))
W, _ = run("close all force; worldmap([-10 30], [-10 30]); h = geoshow('landareas.shp', 'FaceColor', [0.5 0.7 0.5]); n = numel(h); c = get(h(1), 'FaceColor'); t = get(h(1), 'Type'); "
           "x = get(h(1), 'XData'); nn = nnz(isnan(x)); f = gcf;")
same("geoshow('landareas.shp') on a map: a patch a feature, in the colour given", (W['n'], v(W['c']).tolist(), text(W['t'])), (2.0, [0.5, 0.7, 0.5], 'patch'))
pj = [c for c in serialize_figure(W['f'])['axes'][0]['children'] if c.get('type') == 'patch']
same('the island and its hole in one patch, drawn as rings (the hole stays open)', (W['nn'], len(pj), all(c['rings'] for c in pj)), (2.0, 2, True))
W, _ = run("close all force; worldmap([0 10], [0 10]); h = geoshow([-5 -5 5 5 -5], [-5 5 5 -5 -5], 'DisplayType', 'polygon'); [la, lo] = minvtran(get(h, 'XData'), get(h, 'YData')); "
           "ok = isfinite(la); r = [min(la(ok)) max(la(ok)) min(lo(ok)) max(lo(ok))]; nn = nnz(~ok);")
near('a polygon across the map limits is cut along them (no chord across the map)', W['r'], [0, 5, 0, 5], 1e-5)
same('and stays one ring', W['nn'], 1.0)
W, _ = run("close all force; axesm('robinson'); h = geoshow([-20 -15 -15 -20 -20], [175 175 180 180 175], 'DisplayType', 'polygon'); x = get(h, 'XData'); "
           "[xa, ~] = mfwdtran(-17.5, 175); [xb, ~] = mfwdtran(-17.5, 179.999); [xc, ~] = mfwdtran(-20, 175); s = [min(x) - min(xa, xc), max(x) - xb];")
C('a ring that touches 180 degrees stays on its side of the map', bool(np.all(np.abs(v(W['s'])) < 0.02)), str(v(W['s'])))
W, _ = run("close all force; axesm('robinson'); lo = -180:10:180; h = geoshow([-70*ones(size(lo)) -90 -90 -70], [lo 180 -180 -180], 'DisplayType', 'polygon'); "
           "[la, ~] = minvtran(get(h, 'XData'), get(h, 'YData')); r = [min(la) max(la)]; nn = nnz(isnan(get(h, 'XData')));")
near("a ring round the south pole (as Antarctica's) is filled to the pole", v(W['r']).tolist() + [W['nn']], [-90, -70, 1], 1e-5)
W, _ = run("close all force; axesm('ortho', 'Origin', [60 20 0]); h = geoshow([0 0 10 10 0], [100 130 130 100 100], 'DisplayType', 'polygon'); [la, lo] = minvtran(get(h, 'XData'), get(h, 'YData')); "
           "ok = isfinite(la); d = distance(60, 20, la(ok), lo(ok)); r = [max(d) nnz(ok) > 3];")
C('on a globe a polygon past the visible side is cut at the frame circle', W['r'][0, 0] <= 89.9 + 1e-6 and W['r'][0, 1] == 1, str(W['r']))
W, _ = run("close all force; axesm('stereo', 'Origin', [-90 0 0]); h = geoshow([-30 -30 10 10 -30], [10 20 20 10 10], 'DisplayType', 'polygon'); [la, lo] = minvtran(get(h, 'XData'), get(h, 'YData')); "
           "ok = isfinite(la); r = [min(lo(ok)) max(lo(ok)) min(la(ok)) max(la(ok))];")
near('about a pole too: cut at the frame (the equator here), every point between its meridians', W['r'], [10, 20, -30, 0], 1e-5)
W, _ = run("close all force; axesm('stereo', 'Origin', [-90 0 0]); [la, lo] = minvtran([NaN 0], [NaN 0]);")
same('minvtran keeps NaN as NaN', [math.isnan(t) for t in v(W['la']).tolist() + v(W['lo']).tolist()], [True, False, True, False])
n_asked = len(ASKED)
W, _ = run("load coastlines; S = shaperead('landareas'); m = numel(S);")
same('each data set is fetched once a session', len(ASKED), n_asked)
same('without UseGeoCoords the coordinates are X and Y', W['m'], 2.0)
os.makedirs(os.path.join(TMP, 'own'), exist_ok=True)
W, _ = run("cd own; coastlat = [1; 2]; coastlon = [3; 4]; save coastlines coastlat coastlon; clear; load coastlines; a = coastlat'; "
           "S = struct('Geometry', 'Point', 'X', 1, 'Y', 2, 'Name', 'mine'); shapewrite(S, 'landareas.shp'); T = shaperead('landareas'); nm = T.Name; cd ..")
same("a program's own coastlines.mat and landareas.shp come first", (v(W['a']).tolist(), text(W['nm'])), ([1.0, 2.0], 'mine'))
raises("shaperead('nosuch.shp')", 'Unable to find the shapefile')
raises("load nosuchdata", 'Unable to find file')
GD.FETCH = None
GD._CACHE.clear()
raises("load coastlines", 'cannot be fetched here')

# ---- basemaps --------------------------------------------------------------------------------------------------------------------
W, _ = run("close all force; geoplot([59.3 57.7], [18.1 12.0]); b0 = geobasemap; f = gcf;")
same('geographic axes have no basemap until a program names one', (text(W['b0']), serialize_figure(W['f'])['axes'][0]['basemap']), ('none', 'none'))
W, _ = run("close all force; geoplot([59.3 57.7], [18.1 12.0]); geobasemap satellite; b1 = geobasemap; gx = gca; gx.Basemap = 'Topographic'; b2 = gx.Basemap; "
           "set(gx, 'Basemap', 'streets-dark'); b3 = get(gx, 'Basemap'); f = gcf; p = any(strcmp(properties(gx), 'Basemap'));")
same('geobasemap, the Basemap property, set and get', (text(W['b1']), text(W['b2']), text(W['b3'])), ('satellite', 'topographic', 'streets-dark'))
same('the page is told the basemap', (serialize_figure(W['f'])['axes'][0]['basemap'], serialize_figure(W['f'])['axes'][0]['basemapCustom']), ('streets-dark', None))
W, _ = run("close all force; gx = geoaxes('Basemap', 'grayland'); b = gx.Basemap; t = gx.Type; figure; geobubble([59 60], [18 19], [1 2], 'Basemap', 'bluegreen'); c = geobasemap;")
same('geoaxes and geobubble take a Basemap', (text(W['b']), text(W['t']), text(W['c'])), ('grayland', 'geoaxes', 'bluegreen'))
raises("close all force; geoplot(1, 2); geobasemap('nosuchmap')", 'is not a basemap')
W, _ = run("close all force; geoplot(59, 18); geobasemap topographic; a = gca; f2 = figure; b = copyobj(a, f2); geobasemap(b, 'satellite'); ka = geobasemap(a); kb = b.Basemap;")
same("copyobj: the copy's basemap is its own", (text(W['ka']), text(W['kb'])), ('topographic', 'satellite'))
W, _ = run("close all force; addCustomBasemap('mymap', 'https://tiles.example.org/${z}/${x}/${y}.png', 'Attribution', 'Tiles by example', 'MaxZoomLevel', 12); "
           "geoplot(59, 18); geobasemap mymap; b = geobasemap; f = gcf;")
same('addCustomBasemap: its tiles, attribution and zoom go to the page', (text(W['b']), serialize_figure(W['f'])['axes'][0]['basemapCustom']),
     ('mymap', {'url': 'https://tiles.example.org/{z}/{x}/{y}.png', 'note': 'Tiles by example', 'label': 'mymap', 'max': 12}))
raises("addCustomBasemap('x2', 'https://tiles.example.org/a.png')", 'has ${x}, ${y} and ${z}')
raises("addCustomBasemap('streets', 'https://t.example.org/${z}/${x}/${y}.png')", 'is the name of a basemap already')
W, _ = run("removeCustomBasemap('mymap'); try, geoplot(1, 2); geobasemap mymap; e = ''; catch ex, e = ex.message; end")
C('removeCustomBasemap: the name is gone', 'is not a basemap' in text(W['e']), text(W['e']))

W, _ = run("h = geobubble([59.33 59.91 55.68 60.17], [18.07 10.75 12.57 24.94], [1 0.7 0.65 0.66], categorical({'large', 'mid', 'mid', 'mid'})); "
           "n = numel(h); d = {h.DisplayName}; nm = numel(h(2).XData); l = findobj(gcf, 'Type', 'legend'); ls = l.String; br = get(gca, 'BubbleSizeRange'); close all")
same('geobubble with categories: a bubble chart for each, named in the legend, bubbles 5 to 20 points',
     (float(W['n']), [text(x) for x in W['d'].a.reshape(-1)], float(W['nm']), [text(x) for x in W['ls'].a.reshape(-1)], v(W['br']).tolist()),
     (2.0, ['large', 'mid'], 3.0, ['large', 'mid'], [5.0, 20.0]))

W, _ = run("Rc = georefcells([55 70], [10 25], [15 30]); c = [Rc.CellExtentInLatitude Rc.CellExtentInLongitude]; k = class(Rc.CellExtentInLatitude);")
same("a raster reference's numbers are doubles that concatenate", (v(W['c']).tolist(), text(W['k'])), ([1.0, 0.5], 'double'))

W, _ = run("[lon, lat] = meshgrid(-180:90:180, -90:90:90); Z = lat + lon/1000; axesm('eqdcylin'); h = pcolorm(lat, lon, Z); x1 = h.XData(1, :); close all; "
           "axesm('eqdcylin', 'Origin', [0 100 0]); h2 = pcolorm(lat, lon, Z); x2 = h2.XData(2, :); c2 = h2.CData(2, :); close all")
x1, x2, c2 = v(W['x1']), v(W['x2']), v(W['c2'])
same("a world grid on a map: its east edge on the right, and a grid crossing the map's edge parted there (no face across the map)",
     (np.round(x1, 4).tolist(), int(np.isnan(x2).sum()), bool(np.all(np.diff(x2[np.isfinite(x2)][:2]) > 0)), int(np.isnan(c2).sum())),
     ([-3.1416, -1.5708, 0.0, 1.5708, 3.1416], 1, True, 1))
seg = np.split(x2, np.nonzero(np.isnan(x2))[0])
C('each part of the parted grid runs west to east', all(np.all(np.diff(p[np.isfinite(p)]) > 0) for p in seg), x2.tolist())
W, _ = run("axesm('robinson'); [lon, lat] = meshgrid(-180:30:180, -90:30:90); [C, hc] = contourm(lat, lon, lat, 3, 'k--'); cc = hc.Color; cs = hc.LineStyle; "
           "p = geoshow([55 62 66 58 55], [12 8 20 25 12], 'DisplayType', 'polygon', 'FaceColor', 'none', 'EdgeColor', 'r'); pf = p.FaceColor; close all; "
           "g = geoplot([59.65 51.47], [17.92 -0.45], 'b--', [50 55 60], [0 5 10], 'r', 'LineWidth', 1.5); gx = g(2).XData; gy = g(2).YData; gw = [g.LineWidth]; close all")
same("contourm takes a LineSpec; geoshow's FaceColor 'none' leaves a polygon open; geoplot turns each group of lat, lon",
     (v(W['cc']).tolist(), text(W['cs']), text(W['pf']), v(W['gx']).tolist(), v(W['gy']).tolist(), v(W['gw']).tolist()),
     ([0.0, 0.0, 0.0], '--', 'none', [0.0, 5.0, 10.0], [50.0, 55.0, 60.0], [1.5, 1.5]))

# ---- GeoTIFF ------------------------------------------------------------------------------------------------------------------------
try:
    from PIL import Image, TiffImagePlugin
    A = np.arange(20 * 30, dtype=np.float32).reshape(20, 30)
    ifd = TiffImagePlugin.ImageFileDirectory_v2()
    ifd[33550] = (0.5, 0.25, 0.0)
    ifd.tagtype[33550] = 12
    ifd[33922] = (0.0, 0.0, 0.0, 10.0, 60.0, 0.0)
    ifd.tagtype[33922] = 12
    ifd[34735] = (1, 1, 0, 2, 1024, 0, 1, 2, 1025, 0, 1, 1)
    ifd.tagtype[34735] = 3
    Image.fromarray(A, mode='F').save(os.path.join(TMP, 'geo.tif'), tiffinfo=ifd)
    W, _ = run("[A, R] = readgeoraster('geo.tif'); s = size(A); la = R.LatitudeLimits; lo = R.LongitudeLimits; c = R.CellExtentInLatitude; k = class(R); v1 = geointerp(A, R, 59.875, 10.25); v2 = geointerp(A, R, 55.125, 24.75); v3 = geointerp(A, R, 50, 10);")
    near('readgeoraster: size, limits and cells from the GeoTIFF tags', (W['s'], W['la'], W['lo'], W['c']), [20, 30, 55, 60, 10, 25, 0.25])
    near('the first row is the north; geointerp at cell centres; NaN outside', (W['v1'], W['v2']), [0, 599], 1e-9)
    C('geointerp outside the raster is NaN', math.isnan(float(W['v3'])), str(W['v3']))
    W, _ = run("R = georefcells([55 69], [10 25], [14 15]); [lon, lat] = meshgrid(10.5:24.5, 55.5:68.5); A = lat + lon/100; geotiffwrite('w.tif', A, R); "
               "[B, R2] = readgeoraster('w.tif'); kb = class(B); dB = max(max(abs(double(B) - flipud(A)))); la = R2.LatitudeLimits; lo = R2.LongitudeLimits; "
               "g1 = geointerp(A, R, 60.2, 15.3); g2 = geointerp(double(B), R2, 60.2, 15.3); "
               "P = maprefpostings([500000 510000], [6400000 6405000], [6 11]); M = uint16(reshape(1:66, 6, 11)); geotiffwrite('p.tif', M, P, 'CoordRefSysCode', 3006); "
               "[Cm, R3] = readgeoraster('p.tif'); same = isequal(Cm, flipud(M)); xl = R3.XWorldLimits; yl = R3.YWorldLimits; ri = R3.RasterInterpretation; pn = R3.ProjectedCRS.Name;")
    same('geotiffwrite and back: single values, rows from the north, the same limits, geointerp agrees', (text(W['kb']), float(W['dB']) < 1e-5, v(W['la']).tolist(), v(W['lo']).tolist(), abs(float(W['g1']) - float(W['g2'])) < 1e-5),
         ('single', True, [55.0, 69.0], [10.0, 25.0], True))
    same('a projected raster of postings with its EPSG code: values, limits, interpretation and system kept',
         (bool(W['same']), v(W['xl']).tolist(), v(W['yl']).tolist(), text(W['ri']), text(W['pn'])), (True, [500000.0, 510000.0], [6400000.0, 6405000.0], 'postings', 'SWEREF99 TM'))
    raises("geotiffwrite('x.tif', ones(3), georefcells([0 1], [0 1], [2 2]))", 'raster reference is for 2x2')
except ImportError:
    print('(Pillow is not installed: the GeoTIFF checks are skipped)')

sys.exit(C.done())
