"""Mapping: units of distance and angle, reference ellipsoids, geodesy on
the sphere and the ellipsoid (distance, azimuth, reckon, tracks, areas),
Earth-centred and local coordinates (ECEF, ENU, NED, AER), polygons,
projected coordinate systems (projcrs, projfwd, projinv), map axes (axesm,
worldmap, plotm and the rest, frame, graticule and labels), geographic
axes (geoplot, geoscatter, geobubble, geolimits) and shapefiles and GeoTIFF
rasters (shaperead, shapewrite, readgeoraster).

The formulas are in mapproj.py. A map axes is an ordinary axes, its axis
hidden and its aspect equal, with its projection kept here (MAPS) and its
frame, graticule and labels drawn as lines and text tagged as such.
"""
import math
import os
import struct
import datetime

import numpy as np

from . import bi, REG
from ._util import err, darr, out, opt_str, opt_lower, num, is_str, sval
from ..values import MError, Char, Cell, Struct, Str, FH, Obj, EMPTY, F64, numel, py_str
from .. import runtime as R
from .. import mapproj as M
from .. import geodata as GD

D2R, R2D = M.D2R, M.R2D

# ---- units ---------------------------------------------------------------------------------------------------

_LENGTH = {'meter': 1.0, 'm': 1.0, 'meters': 1.0, 'metre': 1.0, 'kilometer': 1000.0, 'km': 1000.0, 'kilometers': 1000.0,
           'kilometre': 1000.0, 'centimeter': 0.01, 'cm': 0.01, 'millimeter': 0.001, 'mm': 0.001, 'micron': 1e-6,
           'nauticalmile': 1852.0, 'nm': 1852.0, 'nauticalmiles': 1852.0, 'nautical mile': 1852.0,
           'foot': 0.3048, 'ft': 0.3048, 'feet': 0.3048, 'internationalfoot': 0.3048, 'surveyfoot': 1200 / 3937, 'sf': 1200 / 3937,
           'u.s. survey foot': 1200 / 3937, 'mile': 1609.344, 'mi': 1609.344, 'miles': 1609.344, 'statutemile': 1609.344, 'sm': 1609.344,
           'statute mile': 1609.344, 'yard': 0.9144, 'yd': 0.9144, 'inch': 0.0254, 'in': 0.0254}
_ANGLE = {'degree': 1.0, 'degrees': 1.0, 'deg': 1.0, 'radian': R2D, 'radians': R2D, 'rad': R2D}


def _length_unit(u, fn):
    k = u.lower().strip()
    if k not in _LENGTH:
        raise err('map:validate:invalidLengthUnit', f"'{u}' is not a unit of length: use meter, kilometer, nauticalmile, mile, foot, ...", fn)
    return _LENGTH[k]


@bi('unitsratio')
def unitsratio(nargout, *args):
    if len(args) != 2:
        raise err('MATLAB:minrhs' if len(args) < 2 else 'MATLAB:TooManyInputs', 'unitsratio takes two units.', 'unitsratio')
    to, frm = sval(args[0], 'unit', 'unitsratio').lower(), sval(args[1], 'unit', 'unitsratio').lower()
    if to in _ANGLE and frm in _ANGLE:
        return _ANGLE[frm] / _ANGLE[to]
    return _length_unit(frm, 'unitsratio') / _length_unit(to, 'unitsratio')


EARTH_KM = 6371.0


def _radius_km(args, i, fn):
    """The radius in km of a conversion: a number, a body's name, or the Earth's 6371 km."""
    if len(args) > i:
        v = args[i]
        if is_str(v):
            s = py_str(v).lower()
            if s in M.SPHERES:
                return M.SPHERES[s] / 1000.0
            raise err('map:validate:unknownBody', f"'{py_str(v)}' is not a body known here: use {', '.join(sorted(M.SPHERES))}.", fn)
        if isinstance(v, RefEllipsoid):
            return v.mean_radius() * v.scale / 1000.0
        return num(v)
    return EARTH_KM


def _conv(fn, factor):
    def f(nargout, *args):
        x = darr(args[0])
        return out(x * factor(args))
    return f


for _name, _f in {
    'deg2km': lambda a: _radius_km(a, 1, 'deg2km') * D2R, 'km2deg': lambda a: R2D / _radius_km(a, 1, 'km2deg'),
    'deg2nm': lambda a: _radius_km(a, 1, 'deg2nm') * D2R / 1.852, 'nm2deg': lambda a: 1.852 * R2D / _radius_km(a, 1, 'nm2deg'),
    'deg2sm': lambda a: _radius_km(a, 1, 'deg2sm') * D2R / 1.609344, 'sm2deg': lambda a: 1.609344 * R2D / _radius_km(a, 1, 'sm2deg'),
    'km2nm': lambda a: 1 / 1.852, 'nm2km': lambda a: 1.852, 'km2sm': lambda a: 1 / 1.609344, 'sm2km': lambda a: 1.609344,
    'nm2sm': lambda a: 1.852 / 1.609344, 'sm2nm': lambda a: 1.609344 / 1.852,
    'km2rad': lambda a: 1 / _radius_km(a, 1, 'km2rad'), 'rad2km': lambda a: _radius_km(a, 1, 'rad2km'),
}.items():
    bi(_name)(_conv(_name, _f))


@bi('dms2degrees')
def dms2degrees(nargout, *args):
    a = darr(args[0])
    if a.ndim != 2 or a.shape[1] != 3:
        raise err('map:dms2degrees:shape', 'The input must have three columns: degrees, minutes and seconds.', 'dms2degrees')
    sgn = np.where((a[:, 0] < 0) | ((a[:, 0] == 0) & (a[:, 1] < 0)) | ((a[:, 0] == 0) & (a[:, 1] == 0) & (a[:, 2] < 0)), -1.0, 1.0)
    return out((sgn * (np.abs(a[:, 0]) + np.abs(a[:, 1]) / 60 + np.abs(a[:, 2]) / 3600)).reshape(-1, 1))


@bi('dm2degrees')
def dm2degrees(nargout, *args):
    a = darr(args[0])
    if a.ndim != 2 or a.shape[1] != 2:
        raise err('map:dm2degrees:shape', 'The input must have two columns: degrees and minutes.', 'dm2degrees')
    sgn = np.where((a[:, 0] < 0) | ((a[:, 0] == 0) & (a[:, 1] < 0)), -1.0, 1.0)
    return out((sgn * (np.abs(a[:, 0]) + np.abs(a[:, 1]) / 60)).reshape(-1, 1))


def _split_signed(x, parts):
    x = np.asarray(x, float).reshape(-1)
    s = np.sign(x)
    v = np.abs(x)
    d = np.floor(v)
    m = (v - d) * 60
    if parts == 2:
        cols = [d, m]
    else:
        mi = np.floor(m + 1e-9)
        sec = (m - mi) * 60
        cols = [d, mi, sec]
    cols = np.column_stack(cols)
    for i in range(cols.shape[0]):
        if s[i] < 0:
            j = next((k for k in range(cols.shape[1]) if cols[i, k] != 0), cols.shape[1] - 1)
            cols[i, j] = -cols[i, j]
    return cols


@bi('degrees2dms')
def degrees2dms(nargout, *args):
    return out(_split_signed(darr(args[0]), 3))


@bi('degrees2dm')
def degrees2dm(nargout, *args):
    return out(_split_signed(darr(args[0]), 2))


def _wrap(x, period, positive):
    x = darr(x).copy()
    half = period / 2
    if positive:
        pos = x > 0
        x = np.mod(x, period)
        x[(x == 0) & pos] = period
    else:
        q = (x < -half) | (x > half)
        y = np.mod(x[q] + half, period)
        y[(y == 0) & (x[q] + half > 0)] = period
        x[q] = y - half
    return out(x)


bi('wrapTo180')(lambda nargout, *args: _wrap(args[0], 360.0, False))
bi('wrapTo360')(lambda nargout, *args: _wrap(args[0], 360.0, True))
bi('wrapToPi')(lambda nargout, *args: _wrap(args[0], 2 * math.pi, False))
bi('wrapTo2Pi')(lambda nargout, *args: _wrap(args[0], 2 * math.pi, True))


# ---- reference ellipsoids ------------------------------------------------------------------------------------------

class RefEllipsoid(Obj):
    """referenceEllipsoid, wgs84Ellipsoid and referenceSphere: an ellipsoid
    (or sphere) in a unit of length."""
    __slots__ = ('a', 'e', 'inv', 'code', 'name', 'unit', 'scale', 'sphere')
    is_handle = False

    def __init__(self, a, e, inv, code, name, unit='meter', sphere=False):
        self.a, self.e, self.inv, self.code, self.name = a, e, inv, code, name
        self.unit = unit
        self.scale = 1.0 / _length_unit(unit, 'referenceEllipsoid')
        self.sphere = sphere

    @property
    def cls(self):
        return 'referenceSphere' if self.sphere else 'referenceEllipsoid'

    def value_copy(self):
        c = RefEllipsoid(self.a, self.e, self.inv, self.code, self.name, self.unit, self.sphere)
        return c

    @property
    def b(self):
        return self.a * math.sqrt(1 - self.e * self.e)

    def mean_radius(self):
        return (2 * self.a + self.b) / 3 if not self.sphere else self.a

    def area(self):
        a, e = self.a, self.e
        if e == 0:
            return 4 * math.pi * a * a
        return 2 * math.pi * a * a * (1 + (1 - e * e) / e * math.atanh(e))

    def props(self):
        s = self.scale
        f = 0.0 if self.e == 0 else 1 / self.inv
        n = f / (2 - f) if f else 0.0
        d = {'Code': float(self.code) if self.code else EMPTY(), 'Name': Char.of(self.name), 'LengthUnit': Char.of(self.unit),
             'SemimajorAxis': self.a * s, 'SemiminorAxis': self.b * s, 'InverseFlattening': self.inv if self.e else math.inf,
             'Eccentricity': self.e, 'Flattening': f, 'ThirdFlattening': n, 'MeanRadius': self.mean_radius() * s,
             'SurfaceArea': self.area() * s * s, 'Volume': 4 / 3 * math.pi * self.a * self.a * self.b * s ** 3}
        if self.sphere:
            d = {'Name': d['Name'], 'LengthUnit': d['LengthUnit'], 'Radius': self.a * s, 'SemimajorAxis': d['SemimajorAxis'],
                 'SemiminorAxis': d['SemiminorAxis'], 'InverseFlattening': math.inf, 'Eccentricity': 0.0, 'Flattening': 0.0,
                 'ThirdFlattening': 0.0, 'MeanRadius': d['MeanRadius'], 'SurfaceArea': d['SurfaceArea'], 'Volume': d['Volume']}
        return d

    def getprop(self, name):
        p = self.props()
        for k, v in p.items():
            if k.lower() == name.lower():
                return v
        return super().getprop(name)

    def setprop(self, name, value):
        if name.lower() == 'lengthunit':
            u = py_str(value)
            _length_unit(u, 'referenceEllipsoid')
            self.unit = u
            self.scale = 1.0 / _LENGTH[u.lower()]
            return
        raise err('map:ellipsoid:readOnly', f"{name} of a {self.cls} cannot be set here; LengthUnit can.")

    def propnames(self):
        return list(self.props())

    def display_lines(self):
        p = self.props()
        w = max(len(k) for k in p)
        lines = [f'{self.cls} with defining properties:', '']
        for k, v in p.items():
            sv = f"'{v.str()}'" if isinstance(v, Char) else ('Inf' if v == math.inf else f'{v:.10g}' if isinstance(v, float) else '[]')
            lines.append(f'  {k.rjust(w)}: {sv}')
        return lines

    def ae_m(self):
        return self.a, self.e


@bi('referenceEllipsoid', arr=False)
def referenceEllipsoid(nargout, *args):
    name = args[0] if args else Char.of('wgs84')
    unit = py_str(args[1]) if len(args) > 1 else 'meter'
    if is_str(name):
        r = M.ellipsoid_ae(py_str(name))
        if r is None:
            s = py_str(name).lower()
            if s in M.SPHERES:
                return RefEllipsoid(M.SPHERES[s], 0.0, math.inf, None, s.capitalize(), unit, sphere=True)
            raise err('map:referenceEllipsoid:unknown', f"'{py_str(name)}' is not an ellipsoid known here: use {', '.join(sorted(M.ELLIPSOIDS))}.", 'referenceEllipsoid')
    else:
        key = M.epsg_ellipsoid(int(num(name)))
        if key is None:
            raise err('map:referenceEllipsoid:unknown', f'{int(num(name))} is not the EPSG code of an ellipsoid known here.', 'referenceEllipsoid')
        r = M.ellipsoid_ae(key)
    a, e, inv, code, full = r
    return RefEllipsoid(a, e, inv, code, full, unit)


@bi('wgs84Ellipsoid', arr=False)
def wgs84Ellipsoid(nargout, *args):
    return referenceEllipsoid(1, Char.of('wgs84'), *args)


@bi('referenceSphere', arr=False)
def referenceSphere(nargout, *args):
    name = py_str(args[0]).lower() if args else 'unit sphere'
    unit = py_str(args[1]) if len(args) > 1 else 'meter'
    if name not in M.SPHERES:
        raise err('map:referenceSphere:unknown', f"'{name}' is not a body known here: use {', '.join(sorted(M.SPHERES))}.", 'referenceSphere')
    return RefEllipsoid(M.SPHERES[name], 0.0, math.inf, None, 'Unit Sphere' if name == 'unit sphere' else name.capitalize(), unit, sphere=True)


@bi('earthRadius')
def earthRadius(nargout, *args):
    unit = py_str(args[0]) if args else 'meter'
    return 6371000.0 / _length_unit(unit, 'earthRadius')


def _ellipsoid(v, fn):
    """(a, e, scale to output units): an ellipsoid object, [a e], or None."""
    if isinstance(v, RefEllipsoid):
        return v.a * v.scale, v.e
    a = darr(v).reshape(-1)
    if a.size == 1:
        return float(a[0]), 0.0
    if a.size == 2:
        return float(a[0]), float(a[1])
    raise err('map:validate:invalidEllipsoid', 'An ellipsoid is a referenceEllipsoid, a referenceSphere or a vector [a e].', fn)


def _is_ell(v):
    return isinstance(v, RefEllipsoid) or (type(v) is np.ndarray and v.size == 2 and v.dtype.kind == 'f')


# ---- geodesy ----------------------------------------------------------------------------------------------------------

def _units_last(args):
    """An 'degrees' or 'radians' at the end: (the rest, True for radians)."""
    args = list(args)
    rad = False
    if args and opt_str(args[-1]) is not None and opt_lower(args[-1]) in ('degrees', 'radians', 'deg', 'rad'):
        rad = opt_lower(args.pop()).startswith('rad')
    return args, rad


def _track_kind(args):
    args = list(args)
    kind = 'gc'
    if args and opt_str(args[0]) is not None and opt_lower(args[0]) in ('gc', 'rh'):
        kind = opt_lower(args.pop(0))
    return args, kind


def _latlon_pairs(args, n):
    """lat1, lon1, lat2, lon2 or [lat1 lon1], [lat2 lon2]."""
    if len(args) >= 2 and np.ndim(darr(args[0])) == 2 and darr(args[0]).shape[-1] == 2 and (len(args) == 2 or not _is_num_like(args[2])):
        a, b = darr(args[0]), darr(args[1])
        return [a[:, 0], a[:, 1], b[:, 0], b[:, 1]], list(args[2:])
    if len(args) < n:
        raise err('map:validate:points', 'Give lat1, lon1, lat2 and lon2, or two points [lat lon] (one per row).')
    return [darr(a) for a in args[:n]], list(args[n:])


def _is_num_like(v):
    return type(v) in (float, np.ndarray) and not _is_ell(v)


def _shape_out(vals, ref):
    shape = np.broadcast(*[darr(r) for r in ref]).shape
    return out(np.asarray(vals, float).reshape(shape) if np.size(vals) == math.prod(shape) else np.asarray(vals, float))


@bi('distance', nout=2)
def distance(nargout, *args):
    args, rad = _units_last(args)
    args, kind = _track_kind(args)
    (lat1, lon1, lat2, lon2), rest = _latlon_pairs(args, 4)
    if rad:
        lat1, lon1, lat2, lon2 = (v * R2D for v in (lat1, lon1, lat2, lon2))
    ell = rest[0] if rest else None
    if ell is None:
        if kind == 'gc':
            d, az = M.gc_inverse(lat1, lon1, lat2, lon2)
        else:
            d, az = M.rhumb_inverse(lat1, lon1, lat2, lon2, 1.0, 0.0)
        d = d if rad else d * R2D
    else:
        a, e = _ellipsoid(ell, 'distance')
        if kind == 'gc':
            d, az = M.vincenty_inverse(lat1, lon1, lat2, lon2, a, e) if e else M.gc_inverse(lat1, lon1, lat2, lon2)
            if not e:
                d = a * d
        else:
            d, az = M.rhumb_inverse(lat1, lon1, lat2, lon2, a, e)
    az = np.mod(az, 2 * math.pi)
    az = az if rad else az * R2D
    shape = np.broadcast(lat1, lon1, lat2, lon2).shape
    d = out(np.asarray(d, float).reshape(shape) if np.ndim(d) else np.full(shape, float(d)))
    if nargout > 1:
        return d, out(np.asarray(az, float).reshape(shape))
    return d


@bi('azimuth')
def azimuth(nargout, *args):
    r = distance(2, *args)
    return r[1]


@bi('reckon', nout=2)
def reckon(nargout, *args):
    args, rad = _units_last(args)
    args, kind = _track_kind(args)
    lat, lon, arclen, az = (darr(a) for a in args[:4])
    ell = args[4] if len(args) > 4 else None
    if rad:
        lat, lon, az = lat * R2D, lon * R2D, az * R2D
        if ell is None:
            arclen = arclen * R2D
    azr = az * D2R
    if ell is None:
        if kind == 'gc':
            la, lo = M.gc_direct(lat, lon, arclen * D2R, azr)
        else:
            la, lo = M.rhumb_direct(lat, lon, arclen * D2R, azr, 1.0, 0.0)
    else:
        a, e = _ellipsoid(ell, 'reckon')
        if kind == 'gc':
            la, lo = M.vincenty_direct(lat, lon, arclen, azr, a, e) if e else M.gc_direct(lat, lon, arclen / a, azr)
        else:
            la, lo = M.rhumb_direct(lat, lon, arclen, azr, a, e)
    lo = (np.asarray(lo) + 180) % 360 - 180
    la, lo = np.asarray(la, float), np.asarray(lo, float)
    if rad:
        la, lo = la * D2R, lo * D2R
    shape = np.broadcast(lat, lon, arclen, az).shape
    la, lo = out(la.reshape(shape)), out(lo.reshape(shape))
    if nargout > 1:
        return la, lo
    return out(np.column_stack([np.ravel(la), np.ravel(lo)]))


def _track_points(kind, lat1, lon1, lat2, lon2, ell, n):
    if ell is None:
        a, e = 1.0, 0.0
    else:
        a, e = _ellipsoid(ell, 'track2')
    f = np.linspace(0, 1, n)
    if kind == 'gc':
        if e:
            s, az = M.vincenty_inverse(lat1, lon1, lat2, lon2, a, e)
            la, lo = M.vincenty_direct(np.full(n, lat1), np.full(n, lon1), f * float(s), np.full(n, float(az)), a, e)
        else:
            d, az = M.gc_inverse(lat1, lon1, lat2, lon2)
            la, lo = M.gc_direct(np.full(n, lat1), np.full(n, lon1), f * float(d), np.full(n, float(az)))
    else:
        d, az = M.rhumb_inverse(lat1, lon1, lat2, lon2, a, e)
        la, lo = M.rhumb_direct(np.full(n, lat1), np.full(n, lon1), f * float(d), np.full(n, float(az)), a, e)
    lo = (np.asarray(lo) + 180) % 360 - 180
    return np.asarray(la, float), lo


@bi('track2', nout=2)
def track2(nargout, *args):
    args, rad = _units_last(args)
    args, kind = _track_kind(args)
    lat1, lon1, lat2, lon2 = (darr(a).reshape(-1) for a in args[:4])
    rest = list(args[4:])
    ell = rest.pop(0) if rest and _is_ell(rest[0]) else None
    n = int(num(rest[0])) if rest else 100
    if rad:
        lat1, lon1, lat2, lon2 = (v * R2D for v in (lat1, lon1, lat2, lon2))
    cols_la, cols_lo = [], []
    for i in range(lat1.size):
        la, lo = _track_points(kind, float(lat1[i]), float(lon1[i]), float(lat2[i]), float(lon2[i]), ell, n)
        cols_la.append(la)
        cols_lo.append(lo)
    LA, LO = np.column_stack(cols_la), np.column_stack(cols_lo)
    if rad:
        LA, LO = LA * D2R, LO * D2R
    if nargout > 1:
        return out(LA), out(LO)
    return out(np.column_stack([LA.reshape(-1, order='F'), LO.reshape(-1, order='F')]))


@bi('track1', nout=2)
def track1(nargout, *args):
    args, rad = _units_last(args)
    args, kind = _track_kind(args)
    lat, lon, az = (float(num(a)) for a in args[:3])
    rest = list(args[3:])
    arclen = float(num(rest.pop(0))) if rest and not _is_ell(rest[0]) and not (type(rest[0]) is np.ndarray and rest[0].size == 2) else 360.0
    ell = rest.pop(0) if rest and _is_ell(rest[0]) else None
    n = int(num(rest[0])) if rest else 100
    if rad:
        lat, lon, az = lat * R2D, lon * R2D, az * R2D
    f = np.linspace(0, 1, n)
    if ell is None:
        la, lo = (M.gc_direct if kind == 'gc' else (lambda a1, b1, d, z: M.rhumb_direct(a1, b1, d, z, 1.0, 0.0)))(np.full(n, lat), np.full(n, lon), f * arclen * D2R, np.full(n, az * D2R))
    else:
        a, e = _ellipsoid(ell, 'track1')
        la, lo = (M.vincenty_direct(np.full(n, lat), np.full(n, lon), f * arclen, np.full(n, az * D2R), a, e) if kind == 'gc'
                  else M.rhumb_direct(np.full(n, lat), np.full(n, lon), f * arclen, np.full(n, az * D2R), a, e))
    lo = (np.asarray(lo) + 180) % 360 - 180
    la = np.asarray(la, float)
    if rad:
        la, lo = la * D2R, lo * D2R
    if nargout > 1:
        return out(la.reshape(-1, 1)), out(lo.reshape(-1, 1))
    return out(np.column_stack([la, lo]))


@bi('gcwaypts', nout=2)
def gcwaypts(nargout, *args):
    lat1, lon1, lat2, lon2 = (float(num(a)) for a in args[:4])
    n = int(num(args[4])) if len(args) > 4 else 10
    la, lo = _track_points('gc', lat1, lon1, lat2, lon2, None, n + 1)
    if nargout > 1:
        return out(la.reshape(-1, 1)), out(lo.reshape(-1, 1))
    return out(np.column_stack([la, lo]))


@bi('meridianarc')
def meridianarc(nargout, *args):
    p1, p2 = darr(args[0]), darr(args[1])
    a, e = _ellipsoid(args[2], 'meridianarc') if len(args) > 2 else (1.0, 0.0)
    return out(M.meridian_arc(p2, a, e) - M.meridian_arc(p1, a, e))


@bi('antipode', nout=2)
def antipode(nargout, *args):
    args, rad = _units_last(args)
    lat, lon = darr(args[0]), darr(args[1])
    half = math.pi if rad else 180.0
    lo = (lon + 2 * half) % (2 * half) - half
    return out(-lat), out(lo)


@bi('areaint')
def areaint(nargout, *args):
    """The areas of polygons on the sphere (a fraction of its surface), or on
    the ellipsoid's authalic sphere in its units squared."""
    args, rad = _units_last(args)
    lat, lon = darr(args[0]).reshape(-1), darr(args[1]).reshape(-1)
    ell = args[2] if len(args) > 2 else None
    if rad:
        lat, lon = lat * R2D, lon * R2D
    parts = _nan_parts(lat, lon)
    areas = []
    for la, lo in parts:
        if la.size < 3:
            areas.append(0.0)
            continue
        if la[0] == la[-1] and lo[0] == lo[-1]:
            la, lo = la[:-1], lo[:-1]
        areas.append(_sphere_polygon_area(la, lo) / (4 * math.pi))
    areas = np.array(areas)
    if ell is not None:
        a, e = _ellipsoid(ell, 'areaint')
        Rq = M.authalic_radius(a, e)
        areas = areas * 4 * math.pi * Rq * Rq
    return out(areas.reshape(-1, 1))


def _sphere_polygon_area(la, lo):
    """The area of a polygon of great-circle edges on the unit sphere: 2*pi
    less the sum of its turning angles (the smaller of it and the rest of
    the sphere, as the order of the vertices does not say which side)."""
    p, l = la * D2R, lo * D2R
    V = np.column_stack([np.cos(p) * np.cos(l), np.cos(p) * np.sin(l), np.sin(p)])
    n = V.shape[0]
    if n < 3:
        return 0.0
    turn = 0.0
    for i in range(n):
        a, v, b = V[i - 1], V[i], V[(i + 1) % n]
        t_in = v - a - np.dot(v - a, v) * v
        t_out = b - np.dot(b, v) * v
        ni, no = np.linalg.norm(t_in), np.linalg.norm(t_out)
        if ni == 0 or no == 0:
            continue
        t_in, t_out = t_in / ni, t_out / no
        turn += math.atan2(float(np.dot(v, np.cross(t_in, t_out))), float(np.dot(t_in, t_out)))
    A = (2 * math.pi - turn) % (4 * math.pi)
    return min(A, 4 * math.pi - A)


@bi('areaquad')
def areaquad(nargout, *args):
    args, rad = _units_last(args)
    lat1, lon1, lat2, lon2 = (darr(a) for a in args[:4])
    ell = args[4] if len(args) > 4 else None
    if rad:
        lat1, lon1, lat2, lon2 = (v * R2D for v in (lat1, lon1, lat2, lon2))
    if ell is None:
        frac = np.abs(np.sin(lat2 * D2R) - np.sin(lat1 * D2R)) * np.abs(lon2 - lon1) / 720.0
        return out(frac)
    a, e = _ellipsoid(ell, 'areaquad')
    q = lambda p: M._q(p * D2R, e)
    area = a * a / 2 * np.abs(q(lat2) - q(lat1)) * np.abs(lon2 - lon1) * D2R if e else a * a * np.abs(np.sin(lat2 * D2R) - np.sin(lat1 * D2R)) * np.abs(lon2 - lon1) * D2R
    return out(area)


@bi('interpm', nout=2)
def interpm(nargout, *args):
    lat, lon = darr(args[0]).reshape(-1), darr(args[1]).reshape(-1)
    if lat.size != lon.size:
        raise err('map:interpm:sizes', 'lat and lon must have the same number of elements.', 'interpm')
    maxd = float(num(args[2]))
    method = py_str(args[3]).lower() if len(args) > 3 else 'lin'
    la_o, lo_o = [lat[:1]], [lon[:1]]
    for i in range(1, lat.size):
        a1, b1, a2, b2 = lat[i - 1], lon[i - 1], lat[i], lon[i]
        if not all(map(math.isfinite, (a1, b1, a2, b2))):
            la_o.append([a2])
            lo_o.append([b2])
            continue
        if method == 'gc':
            d = float(M.gc_inverse(a1, b1, a2, b2)[0]) * R2D
            n = max(1, int(math.ceil(d / maxd)))
            la, lo = _track_points('gc', a1, b1, a2, b2, None, n + 1)
            la_o.append(la[1:])
            lo_o.append(lo[1:])
        else:
            n = max(1, int(math.ceil(max(abs(a2 - a1), abs(b2 - b1)) / maxd)))
            f = np.linspace(0, 1, n + 1)[1:]
            la_o.append(a1 + f * (a2 - a1))
            lo_o.append(b1 + f * (b2 - b1))
    la, lo = np.concatenate(la_o), np.concatenate(lo_o)
    return (out(la.reshape(-1, 1)), out(lo.reshape(-1, 1))) if nargout > 1 else out(la.reshape(-1, 1))


def _nan_parts(a, b):
    parts = []
    cur_a, cur_b = [], []
    for x, y in zip(a, b):
        if math.isnan(x) or math.isnan(y):
            if cur_a:
                parts.append((np.array(cur_a), np.array(cur_b)))
            cur_a, cur_b = [], []
        else:
            cur_a.append(x)
            cur_b.append(y)
    if cur_a:
        parts.append((np.array(cur_a), np.array(cur_b)))
    return parts


# ---- ECEF and local frames ------------------------------------------------------------------------------------------------

def _spheroid_first(args, fn):
    """(spheroid (a, e) in its units, the rest, radians?) for the functions
    that take the spheroid first; WGS 84 in meters unless given."""
    args, rad = _units_last(args)
    if args and (isinstance(args[0], RefEllipsoid) or (type(args[0]) is np.ndarray and args[0].size == 2)):
        a, e = _ellipsoid(args[0], fn)
        return (a, e), list(args[1:]), rad
    a, e, *_ = M.ellipsoid_ae('wgs84')
    return (a, e), list(args), rad


def _spheroid_last(args, n, fn):
    """(spheroid, the first n, radians?) for the functions that take it last."""
    args, rad = _units_last(args)
    if len(args) > n and args[n] is not None and (isinstance(args[n], RefEllipsoid) or numel(args[n]) in (1, 2)):
        a, e = _ellipsoid(args[n], fn)
    else:
        a, e, *_ = M.ellipsoid_ae('wgs84')
    return (a, e), [darr(v) for v in args[:n]], rad


def _ang(v, rad):
    return v * R2D if rad else v


def _ang_out(v, rad):
    return v * D2R if rad else v


@bi('geodetic2ecef', nout=3)
def geodetic2ecef(nargout, *args):
    # old form: geodetic2ecef(lat, lon, h, ellipsoid) in radians
    if len(args) == 4 and not isinstance(args[0], RefEllipsoid) and numel(args[3]) == 2 and not is_str(args[3]):
        a, e = _ellipsoid(args[3], 'geodetic2ecef')
        lat, lon, h = (darr(v) for v in args[:3])
        x, y, z = M.geodetic2ecef(lat * R2D, lon * R2D, h, a, e)
        return tuple(out(np.asarray(v)) for v in (x, y, z))[:max(1, nargout)] if nargout > 1 else out(np.asarray(x))
    (a, e), rest, rad = _spheroid_first(args, 'geodetic2ecef')
    lat, lon, h = (darr(v) for v in rest[:3])
    x, y, z = M.geodetic2ecef(_ang(lat, rad), _ang(lon, rad), h, a, e)
    return (out(np.asarray(x)), out(np.asarray(y)), out(np.asarray(z)))[:max(1, nargout)] if nargout > 1 else out(np.asarray(x))


@bi('ecef2geodetic', nout=3)
def ecef2geodetic(nargout, *args):
    if len(args) == 4 and not isinstance(args[0], RefEllipsoid) and numel(args[3]) == 2 and not is_str(args[3]):
        a, e = _ellipsoid(args[3], 'ecef2geodetic')
        x, y, z = (darr(v) for v in args[:3])
        lat, lon, h = M.ecef2geodetic(x, y, z, a, e)
        return (out(lat * D2R), out(lon * D2R), out(h))[:max(1, nargout)] if nargout > 1 else out(lat * D2R)
    (a, e), rest, rad = _spheroid_first(args, 'ecef2geodetic')
    x, y, z = (darr(v) for v in rest[:3])
    lat, lon, h = M.ecef2geodetic(x, y, z, a, e)
    return (out(_ang_out(lat, rad)), out(_ang_out(lon, rad)), out(h))[:max(1, nargout)] if nargout > 1 else out(_ang_out(lat, rad))


def _three(nargout, vals):
    vals = [out(np.asarray(v, float)) for v in vals]
    return tuple(vals)[:max(1, nargout)] if nargout > 1 else vals[0]


def _local_from_ecef(kind):
    def f(nargout, *args):
        (a, e), (x, y, z, lat0, lon0, h0), rad = _spheroid_last(args, 6, f'ecef2{kind}')
        lat0, lon0 = _ang(lat0, rad), _ang(lon0, rad)
        x0, y0, z0 = M.geodetic2ecef(lat0, lon0, h0, a, e)
        E, N, U = M.ecef2enu_vec(x - x0, y - y0, z - z0, lat0, lon0)
        return _three(nargout, _from_enu(kind, E, N, U, rad))
    return f


def _from_enu(kind, E, N, U, rad):
    if kind == 'enu':
        return E, N, U
    if kind == 'ned':
        return N, E, -U
    az, el, r = M.enu2aer(E, N, U)
    return _ang_out(az, rad), _ang_out(el, rad), r


def _to_enu(kind, A, B, C, rad):
    if kind == 'enu':
        return A, B, C
    if kind == 'ned':
        return B, A, -C
    return M.aer2enu(_ang(A, rad), _ang(B, rad), C)


def _ecef_from_local(kind):
    def f(nargout, *args):
        (a, e), (p, q, r, lat0, lon0, h0), rad = _spheroid_last(args, 6, f'{kind}2ecef')
        lat0, lon0 = _ang(lat0, rad), _ang(lon0, rad)
        E, N, U = _to_enu(kind, p, q, r, rad)
        x0, y0, z0 = M.geodetic2ecef(lat0, lon0, h0, a, e)
        dx, dy, dz = M.enu2ecef_vec(E, N, U, lat0, lon0)
        return _three(nargout, (x0 + dx, y0 + dy, z0 + dz))
    return f


def _local_from_geodetic(kind):
    def f(nargout, *args):
        (a, e), (lat, lon, h, lat0, lon0, h0), rad = _spheroid_last(args, 6, f'geodetic2{kind}')
        lat, lon, lat0, lon0 = (_ang(v, rad) for v in (lat, lon, lat0, lon0))
        x, y, z = M.geodetic2ecef(lat, lon, h, a, e)
        x0, y0, z0 = M.geodetic2ecef(lat0, lon0, h0, a, e)
        E, N, U = M.ecef2enu_vec(x - x0, y - y0, z - z0, lat0, lon0)
        return _three(nargout, _from_enu(kind, E, N, U, rad))
    return f


def _geodetic_from_local(kind):
    def f(nargout, *args):
        (a, e), (p, q, r, lat0, lon0, h0), rad = _spheroid_last(args, 6, f'{kind}2geodetic')
        lat0, lon0 = _ang(lat0, rad), _ang(lon0, rad)
        E, N, U = _to_enu(kind, p, q, r, rad)
        x0, y0, z0 = M.geodetic2ecef(lat0, lon0, h0, a, e)
        dx, dy, dz = M.enu2ecef_vec(E, N, U, lat0, lon0)
        lat, lon, h = M.ecef2geodetic(x0 + dx, y0 + dy, z0 + dz, a, e)
        return _three(nargout, (_ang_out(lat, rad), _ang_out(lon, rad), h))
    return f


for _k in ('enu', 'ned', 'aer'):
    bi(f'ecef2{_k}', nout=3)(_local_from_ecef(_k))
    bi(f'{_k}2ecef', nout=3)(_ecef_from_local(_k))
    bi(f'geodetic2{_k}', nout=3)(_local_from_geodetic(_k))
    bi(f'{_k}2geodetic', nout=3)(_geodetic_from_local(_k))


@bi('enu2aer', nout=3)
def enu2aer(nargout, *args):
    args, rad = _units_last(args)
    E, N, U = (darr(v) for v in args[:3])
    return _three(nargout, _from_enu('aer', E, N, U, rad))


@bi('aer2enu', nout=3)
def aer2enu(nargout, *args):
    args, rad = _units_last(args)
    A, B, C = (darr(v) for v in args[:3])
    return _three(nargout, _to_enu('aer', A, B, C, rad))


@bi('ned2aer', nout=3)
def ned2aer(nargout, *args):
    args, rad = _units_last(args)
    N, E, D = (darr(v) for v in args[:3])
    return _three(nargout, _from_enu('aer', E, N, -D, rad))


@bi('aer2ned', nout=3)
def aer2ned(nargout, *args):
    args, rad = _units_last(args)
    if len(args) < 3:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'aer2ned')
    E, N, U = _to_enu('aer', *(darr(v) for v in args[:3]), rad)
    return _three(nargout, (N, E, -U))


# ---- polygons ----------------------------------------------------------------------------------------------------------

@bi('inpolygon', nout=2)
def inpolygon(nargout, *args):
    """Points inside a polygon (or on its edge), by the crossing count;
    NaN-separated parts and holes count as the even-odd rule counts them."""
    xq, yq = darr(args[0]), darr(args[1])
    xv, yv = darr(args[2]).reshape(-1), darr(args[3]).reshape(-1)
    shape = np.broadcast(xq, yq).shape
    px, py = np.broadcast_to(xq, shape).reshape(-1), np.broadcast_to(yq, shape).reshape(-1)
    inside = np.zeros(px.size, bool)
    on = np.zeros(px.size, bool)
    for vx, vy in _nan_parts(xv, yv):
        if vx.size < 2:
            continue
        x1, y1 = vx, vy
        x2, y2 = np.roll(vx, -1), np.roll(vy, -1)
        for k in range(vx.size):
            ax, ay, bx, by = x1[k], y1[k], x2[k], y2[k]
            cross = ((ay > py) != (by > py)) & (px < (bx - ax) * (py - ay) / np.where(by != ay, by - ay, 1) + ax)
            inside ^= cross
            # on the edge: collinear and within the segment
            cr = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
            scale = max(abs(bx - ax), abs(by - ay), 1e-300)
            within = (np.minimum(ax, bx) - 1e-12 * scale <= px) & (px <= np.maximum(ax, bx) + 1e-12 * scale) & \
                     (np.minimum(ay, by) - 1e-12 * scale <= py) & (py <= np.maximum(ay, by) + 1e-12 * scale)
            on |= (np.abs(cr) <= 1e-12 * scale * scale) & within
    r_in = (inside | on).reshape(shape)
    r_on = on.reshape(shape)
    b = lambda a: bool(a.reshape(-1)[0]) if a.size == 1 else a
    return (b(r_in), b(r_on)) if nargout > 1 else b(r_in)


@bi('polyarea')
def polyarea(nargout, *args):
    x, y = darr(args[0]), darr(args[1])
    if x.ndim == 2 and x.shape[0] > 1 and x.shape[1] > 1:
        return out(np.abs(np.sum(x * np.roll(y, -1, 0) - np.roll(x, -1, 0) * y, axis=0)).reshape(1, -1) / 2)
    x, y = x.reshape(-1), y.reshape(-1)
    return float(abs(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)) / 2)


def _signed_area(x, y):
    return float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)) / 2


@bi('ispolycw')
def ispolycw(nargout, *args):
    x, y = darr(args[0]).reshape(-1), darr(args[1]).reshape(-1)
    parts = _nan_parts(x, y)
    r = [(_signed_area(px, py) <= 0) for px, py in parts] or [True]
    return r[0] if len(r) == 1 else np.array([r])


def _orient(args, cw, nargout):
    x, y = darr(args[0]).reshape(-1), darr(args[1]).reshape(-1)
    parts = _nan_parts(x, y)
    xs, ys = [], []
    for i, (px, py) in enumerate(parts):
        if (_signed_area(px, py) <= 0) != cw:
            px, py = px[::-1], py[::-1]
        if i:
            xs.append([math.nan])
            ys.append([math.nan])
        xs.append(px)
        ys.append(py)
    xo = np.concatenate(xs) if xs else np.zeros(0)
    yo = np.concatenate(ys) if ys else np.zeros(0)
    shape = (1, -1) if darr(args[0]).shape[0] == 1 else (-1, 1)
    return (out(xo.reshape(shape)), out(yo.reshape(shape))) if nargout > 1 else out(xo.reshape(shape))


bi('poly2cw', nout=2)(lambda nargout, *args: _orient(args, True, nargout))
bi('poly2ccw', nout=2)(lambda nargout, *args: _orient(args, False, nargout))


@bi('polysplit', nout=2)
def polysplit(nargout, *args):
    x, y = darr(args[0]).reshape(-1), darr(args[1]).reshape(-1)
    parts = _nan_parts(x, y)
    cx, cy = np.empty((len(parts), 1), object), np.empty((len(parts), 1), object)
    for i, (px, py) in enumerate(parts):
        cx[i, 0], cy[i, 0] = out(px.reshape(-1, 1)), out(py.reshape(-1, 1))
    return (Cell(cx), Cell(cy)) if nargout > 1 else Cell(cx)


@bi('polyjoin', nout=2)
def polyjoin(nargout, *args):
    if len(args) != 2 or type(args[0]) is not Cell or type(args[1]) is not Cell:
        raise err('map:polyjoin:cells', 'polyjoin takes two cell arrays of vertex lists.', 'polyjoin')
    xs, ys = [], []
    for i, (a, b) in enumerate(zip(args[0].a.reshape(-1), args[1].a.reshape(-1))):
        if i:
            xs.append([math.nan])
            ys.append([math.nan])
        xs.append(darr(a).reshape(-1))
        ys.append(darr(b).reshape(-1))
    return (out(np.concatenate(xs).reshape(-1, 1)), out(np.concatenate(ys).reshape(-1, 1))) if nargout > 1 else out(np.concatenate(xs).reshape(-1, 1))


@bi('polyxpoly', nout=3)
def polyxpoly(nargout, *args):
    """Where two polylines cross: each segment of one against each of the other."""
    x1, y1, x2, y2 = (darr(a).reshape(-1) for a in args[:4])
    unique = not (len(args) > 4 and is_str(args[4]) and py_str(args[4]).lower() == 'unique') or True
    pts, ii = [], []
    for i in range(x1.size - 1):
        ax, ay, bx, by = x1[i], y1[i], x1[i + 1], y1[i + 1]
        if not all(map(math.isfinite, (ax, ay, bx, by))):
            continue
        for j in range(x2.size - 1):
            cx, cy, dx, dy = x2[j], y2[j], x2[j + 1], y2[j + 1]
            if not all(map(math.isfinite, (cx, cy, dx, dy))):
                continue
            den = (bx - ax) * (dy - cy) - (by - ay) * (dx - cx)
            if den == 0:
                continue
            t = ((cx - ax) * (dy - cy) - (cy - ay) * (dx - cx)) / den
            u = ((cx - ax) * (by - ay) - (cy - ay) * (bx - ax)) / den
            if -1e-12 <= t <= 1 + 1e-12 and -1e-12 <= u <= 1 + 1e-12:
                p = (ax + t * (bx - ax), ay + t * (by - ay))
                if not any(abs(p[0] - q[0]) <= 1e-12 * max(1, abs(q[0])) and abs(p[1] - q[1]) <= 1e-12 * max(1, abs(q[1])) for q in pts):
                    pts.append(p)
                    ii.append((i + 1, j + 1))
    xi = out(np.array([p[0] for p in pts], float).reshape(-1, 1)) if pts else np.zeros((0, 1))
    yi = out(np.array([p[1] for p in pts], float).reshape(-1, 1)) if pts else np.zeros((0, 1))
    if nargout > 2:
        return xi, yi, out(np.array(ii, float).reshape(-1, 2)) if ii else np.zeros((0, 2))
    return (xi, yi) if nargout > 1 else xi


# ---- coordinate reference systems --------------------------------------------------------------------------------------------

class CRS(Obj):
    """projcrs and geocrs: a projected (or geographic) coordinate reference
    system: its projection with its ellipsoid and parameters."""
    __slots__ = ('code', 'name', 'proj', 'kind', 'ell', 'params', 'geo', 'pyproj')
    is_handle = False

    def __init__(self, code, name, kind, ell, params, geo, proj=None, pyproj=None):
        self.code, self.name, self.kind, self.ell, self.params, self.geo = code, name, kind, ell, params, geo
        self.proj = proj
        self.pyproj = pyproj

    @property
    def cls(self):
        return 'geocrs' if self.kind == 'geographic' else 'projcrs'

    def value_copy(self):
        return self

    def props(self):
        d = {'Name': Char.of(self.name)}
        if self.kind != 'geographic':
            d['GeographicCRS'] = geocrs(1, Char.of('code'), float(int(self.geo.split(':')[1]))) if self.geo and self.geo.startswith('EPSG:') and self.geo != 'EPSG:4326' and False else Char.of(self.geo or '')
            d['ProjectionMethod'] = Char.of({'tranmerc': 'Transverse Mercator', 'mercator': 'Mercator', 'lambert': 'Lambert Conic Conformal (2SP)',
                                             'eqaazim': 'Lambert Azimuthal Equal Area', 'eqaconic': 'Albers Equal Area', 'ups': 'Polar Stereographic'}
                                            .get(self.kind, self.kind))
            d['LengthUnit'] = Char.of('meter')
            d['ProjectionParameters'] = Struct.scalar({k: (float(v) if not isinstance(v, list) else out(np.array([v], float))) for k, v in self.params.items()})
        else:
            d['Datum'] = Char.of(self.name)
            d['AngleUnit'] = Char.of('degree')
        d['Spheroid'] = referenceEllipsoid(1, Char.of(self.ell)) if self.ell and M.ellipsoid_ae(self.ell) else EMPTY()
        return d

    def getprop(self, name):
        for k, v in self.props().items():
            if k.lower() == name.lower():
                return v
        return super().getprop(name)

    def propnames(self):
        return list(self.props())

    def display_lines(self):
        p = self.props()
        w = max(len(k) for k in p)
        lines = [f'{self.cls} with properties:', '']
        for k, v in p.items():
            sv = f"'{v.str()}'" if isinstance(v, Char) else (f'[1×1 {getattr(v, "cls", "struct")}]' if not isinstance(v, (float, np.ndarray)) else str(v))
            lines.append(f'  {k.rjust(w)}: {sv}')
        return lines

    def fwd(self, lat, lon):
        if self.pyproj is not None:
            return self.pyproj.transform(lon, lat)
        return self.proj.fwd(lat, lon)

    def inv(self, x, y):
        if self.pyproj is not None:
            lon, lat = self.pyproj.transform(x, y, direction='INVERSE')
            return lat, lon
        return self.proj.inv(x, y)


@bi('projcrs', aw=True, arr=False)
async def projcrs(nargout, *args):
    if not args:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'projcrs')
    v = args[0]
    if is_str(v):
        s = py_str(v).strip()
        if s.upper().startswith('EPSG:'):
            code = int(s.split(':')[1])
        else:
            raise err('map:crs:wkt', 'projcrs takes an EPSG code here, as projcrs(3006) or projcrs("EPSG:3006").', 'projcrs')
    else:
        code = int(num(v))
    if len(args) > 2 and opt_str(args[1]) is not None and opt_lower(args[1]) == 'authority' and py_str(args[2]).upper() != 'EPSG':
        raise err('map:crs:authority', 'Only EPSG codes are known here.', 'projcrs')
    d = M.epsg(code)
    if d is not None:
        name, kind, ell, params, geo = d
        if ell == 'sphere6378137':
            a, e = 6378137.0, 0.0
            ell = 'wgs84'
        else:
            a, e, *_ = M.ellipsoid_ae(ell)
        return CRS(code, name, kind, ell, params, geo, proj=M.make(kind, a, e, **params))
    tr = await _pyproj_transformer(code)
    if tr is None:
        raise err('map:crs:unknownCode', f'EPSG:{code} is not a projected system known here, and PROJ (pyproj) is not available to look it up.', 'projcrs')
    t, name = tr
    return CRS(code, name, 'proj', '', {}, 'EPSG:4326', pyproj=t)


async def _pyproj_transformer(code):
    try:
        import pyproj
    except ImportError:
        import sys
        if sys.platform != 'emscripten':
            return None
        try:
            import pyodide_js
            await pyodide_js.loadPackage('pyproj')
            import pyproj
        except Exception:
            return None
    try:
        crs = pyproj.CRS.from_epsg(code)
    except Exception:
        return None
    if not crs.is_projected:
        return None
    return pyproj.Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True), crs.name


@bi('geocrs', arr=False)
def geocrs(nargout, *args):
    code = int(num(args[0])) if args and not is_str(args[0]) else 4326
    names = {4326: ('WGS 84', 'wgs84'), 4258: ('ETRS89', 'grs80'), 4619: ('SWEREF99', 'grs80'), 4124: ('RT90', 'bessel'),
             4269: ('NAD83', 'grs80'), 4277: ('OSGB36', 'airy1830'), 4171: ('RGF93 v1', 'grs80')}
    if code not in names:
        raise err('map:crs:unknownCode', f"EPSG:{code} is not a geographic system known here: {', '.join(str(c) for c in names)}.", 'geocrs')
    nm, ell = names[code]
    return CRS(code, nm, 'geographic', ell, {}, None)


def _proj_of(v, fn):
    if isinstance(v, CRS):
        return v
    if type(v) is Struct:
        ms = _mstruct_to_state(v)
        return ms
    raise err('map:projfwd:invalidProj', 'The first input must be a projcrs object or a map projection structure.', fn)


@bi('projfwd', nout=2)
def projfwd(nargout, *args):
    p = _proj_of(args[0], 'projfwd')
    lat, lon = darr(args[1]), darr(args[2])
    x, y = p.fwd(lat, lon)
    return (out(np.asarray(x, float)), out(np.asarray(y, float))) if nargout > 1 else out(np.asarray(x, float))


@bi('projinv', nout=2)
def projinv(nargout, *args):
    p = _proj_of(args[0], 'projinv')
    x, y = darr(args[1]), darr(args[2])
    lat, lon = p.inv(x, y)
    return (out(np.asarray(lat, float)), out(np.asarray(lon, float))) if nargout > 1 else out(np.asarray(lat, float))


# ---- map axes -------------------------------------------------------------------------------------------------------------------

MAPS = {}      # axes id -> MapState

_CYL = {'eqdcylin', 'pcarree', 'miller', 'eqacylin', 'mercator', 'robinson', 'sinusoid', 'mollweid', 'hammer', 'equalearth'}
_AZI = {'ortho', 'stereo', 'gnomonic', 'eqdazim', 'eqaazim', 'ups'}
_CONIC = {'lambert', 'lambertstd', 'eqaconic', 'eqaconicstd', 'eqdconic', 'eqdconicstd'}


def _clip_half(x, y, a, b, c):
    """A ring (x, y; its last point joined to its first) clipped to the half
    plane a*x + b*y <= c: one edge of Sutherland and Hodgman's clipping, for
    all the ring's edges at once."""
    s = a * x + b * y - c
    ins = s <= 0
    if ins.all():
        return x, y
    if not ins.any():
        return x[:0], y[:0]
    xn, yn, sn, insn = np.roll(x, -1), np.roll(y, -1), np.roll(s, -1), np.roll(ins, -1)
    cross = ins != insn
    with np.errstate(divide='ignore', invalid='ignore'):
        t = np.where(cross, s / (s - sn), 0.0)
    # each edge gives its crossing (when it crosses) and then its end (when that is inside)
    cnt = cross.astype(np.intp) + insn.astype(np.intp)
    at = np.cumsum(cnt) - cnt
    ox, oy = np.empty(int(cnt.sum())), np.empty(int(cnt.sum()))
    ox[at[cross]] = (x + t * (xn - x))[cross]
    oy[at[cross]] = (y + t * (yn - y))[cross]
    k = (at + cross)[insn]
    ox[k], oy[k] = xn[insn], yn[insn]
    return ox, oy


def _densify(x, y, cut, R=None, step=1.0):
    """A ring with points added along its edges marked cut (those the clipping
    made along the map's limits), a step apart, so that they follow the limits
    once projected: straight in longitude and latitude, or round the frame's
    circle of radius R in the azimuthal plane. Other edges are left as given."""
    xn, yn = np.roll(x, -1), np.roll(y, -1)
    if R is None:
        length = np.hypot(xn - x, yn - y)
    else:
        a0 = np.arctan2(x, y)
        da = (np.arctan2(xn, yn) - a0 + np.pi) % (2 * np.pi) - np.pi
        length = np.abs(da) * R
    m = np.where(cut, np.maximum(1, np.ceil(length / step)), 1).astype(np.intp)     # intp: Pyodide's NumPy is 32-bit
    if m.max() == 1:
        return x, y
    i = np.repeat(np.arange(x.size), m)
    t = (np.arange(int(m.sum())) - np.repeat(np.cumsum(m) - m, m)) / np.repeat(m, m)
    if R is None:
        return x[i] + t * (xn - x)[i], y[i] + t * (yn - y)[i]
    a = a0[i] + t * da[i]
    on = cut[i]
    return np.where(on, R * np.sin(a), x[i]), np.where(on, R * np.cos(a), y[i])


def _azimuthal_plane(lat0, lon0):
    """To and from the plane of the azimuthal equidistant map about (lat0, lon0),
    in degrees: x = d*sin(az), y = d*cos(az). By unit vectors, so that it holds
    at a pole too (where gc_direct's longitude is 0/0)."""
    a, b = lat0 * D2R, lon0 * D2R
    o = np.array([math.cos(a) * math.cos(b), math.cos(a) * math.sin(b), math.sin(a)])
    e = np.array([-math.sin(b), math.cos(b), 0.0])
    n = np.array([-math.sin(a) * math.cos(b), -math.sin(a) * math.sin(b), math.cos(a)])

    def fwd(lat, lon):
        p, q = lat * D2R, lon * D2R
        v = np.stack([np.cos(p) * np.cos(q), np.cos(p) * np.sin(q), np.sin(p)], axis=-1)
        d = np.arccos(np.clip(v @ o, -1.0, 1.0)) * R2D
        az = np.arctan2(v @ e, v @ n)
        return d * np.sin(az), d * np.cos(az)

    def inv(x, y):
        d, az = np.hypot(x, y) * D2R, np.arctan2(x, y)
        v = np.outer(np.cos(d), o) + np.outer(np.sin(d) * np.cos(az), n) + np.outer(np.sin(d) * np.sin(az), e)
        return np.arcsin(np.clip(v[:, 2], -1.0, 1.0)) * R2D, np.arctan2(v[:, 1], v[:, 0]) * R2D
    return fwd, inv


def _rings(lat, lon):
    """The rings of polygons parted by NaN, each without a repeated last point."""
    ok = np.isfinite(lat) & np.isfinite(lon)
    out, k, n = [], 0, lat.size
    while k < n:
        if not ok[k]:
            k += 1
            continue
        j = k
        while j < n and ok[j]:
            j += 1
        la, lo = lat[k:j], lon[k:j]
        if la.size > 1 and la[0] == la[-1] and lo[0] == lo[-1]:
            la, lo = la[:-1], lo[:-1]
        if la.size >= 3:
            out.append((la, lo))
        k = j
    return out


class MapState:
    """A map axes' projection and the look of its frame, graticule and labels."""

    def __init__(self, name='eqdcylin'):
        self.name = name
        self.geoid = (1.0, 0.0)
        self.origin = [0.0, 0.0, 0.0]
        self.latlim = [-90.0, 90.0]
        self.lonlim = [-180.0, 180.0]
        self.parallels = None
        self.fe = self.fn = 0.0
        self.k0 = 1.0
        self.zone = ''
        self.frame = False
        self.grid = False
        self.mlabel = False
        self.plabel = False
        self.mline = 30.0
        self.pline = 15.0
        self.mlabelloc = None
        self.plabelloc = None
        self.mlabelparallel = 'south'
        self.plabelmeridian = 'west'
        self.gcolor = (0.15, 0.15, 0.15)
        self.glinestyle = ':'
        self.glinewidth = 0.5
        self.fedgecolor = (0.15, 0.15, 0.15)
        self.ffacecolor = 'none'
        self.flinewidth = 2.0
        self.fontsize = 9.0
        self.frame_radius = None
        self.proj = None
        self.setup()

    def setup(self):
        name = self.name
        a, e = self.geoid
        kw = dict(lat0=self.origin[0], lon0=self.origin[1], k0=self.k0, fe=self.fe, fn=self.fn)
        if self.parallels is not None:
            kw['parallels'] = list(self.parallels)
        elif name in _CONIC:
            span = self.latlim[1] - self.latlim[0]
            kw['parallels'] = [self.latlim[0] + span / 6, self.latlim[1] - span / 6] if span < 170 else [15.0, 75.0]
        if name == 'utm':
            kw.update(lat0=0.0, k0=0.9996, fe=500000.0 * (a / 6378137.0 if a > 1000 else 0.0))
        if name in _CYL | {'utm', 'tranmerc'} | _CONIC:
            pass
        ee = e if name in ('mercator', 'tranmerc', 'utm', 'lambert', 'lambertstd', 'eqaconic', 'eqaconicstd', 'eqaazim', 'ups', 'eqacylin') else 0.0
        if name == 'ups':
            kw['lat0'] = 90.0 if self.origin[0] >= 0 else -90.0
            kw['k0'] = 0.994
        self.proj = M.make(name, a, ee, **kw)
        if name in _AZI:
            self.frame_radius = {'ortho': 89.9, 'gnomonic': 60.0, 'stereo': 90.0, 'eqdazim': 90.0, 'eqaazim': 90.0}.get(name, None)

    # positions, with the points the map does not show left out (NaN)
    def project(self, lat, lon, cut=True):
        lat = np.asarray(lat, float).reshape(-1)
        lon = np.asarray(lon, float).reshape(-1)
        keep = np.isfinite(lat) & np.isfinite(lon)
        if self.name in _AZI and self.name != 'ups':
            d, _ = M.gc_inverse(self.origin[0], self.origin[1], lat, lon)
            keep &= d * R2D <= (self.frame_radius or 180.0) + 1e-9
            keep &= self.proj.visible(lat, lon)
        elif self.name == 'ups':
            keep &= (lat >= self.latlim[0] - 1e-9) & (lat <= self.latlim[1] + 1e-9)
        else:
            keep &= (lat >= self.latlim[0] - 1e-9) & (lat <= self.latlim[1] + 1e-9)
            dl = (lon - self.origin[1] + 180) % 360 - 180
            lo0, lo1 = (self.lonlim[0] - self.origin[1]), (self.lonlim[1] - self.origin[1])
            keep &= (dl >= lo0 - 1e-9) & (dl <= lo1 + 1e-9) if lo1 - lo0 < 360 - 1e-9 else True
        x, y = self.proj.fwd(np.where(keep, lat, 0.0), np.where(keep, lon, 0.0))
        x = np.where(keep, x, np.nan)
        y = np.where(keep, y, np.nan)
        if cut and self.name not in _AZI and x.size > 1:
            # a line that crosses the edge of the map (the date line about the origin) is broken there
            dl = (lon - self.origin[1] + 180) % 360 - 180
            jump = np.abs(np.diff(dl)) > 180
            if np.any(jump):
                xs, ys = [x[0]], [y[0]]
                for k in range(1, x.size):
                    if jump[k - 1]:
                        xs.append(np.nan)
                        ys.append(np.nan)
                    xs.append(x[k])
                    ys.append(y[k])
                x, y = np.array(xs), np.array(ys)
        return x, y

    def project_polygon(self, lat, lon):
        """Polygons (rings parted by NaN) cut to what the map shows, then
        projected. A ring is clipped to the map's latitude and longitude limits
        (to the frame's circle on an azimuthal map), the cut edges running along
        them; a ring is unwrapped across the map's edge meridian, clipped again
        360 degrees over where it reaches past it, and one that goes round a pole
        (Antarctica's) closed through the pole. Rings come back parted by NaN."""
        lat = np.asarray(lat, float).reshape(-1)
        lon = np.asarray(lon, float).reshape(-1)
        xs, ys = [], []
        o_lat, o_lon = self.origin[0], self.origin[1]
        if self.name in _AZI and self.name != 'ups':
            R = (self.frame_radius or 180.0) * (1 - 1e-9)
            n = 180
            th = (np.arange(n) + 0.5) * 2 * math.pi / n
            fwd, inv = _azimuthal_plane(o_lat, o_lon)
            for la, lo in _rings(lat, lon):
                X, Y = fwd(la, lo)
                d = np.hypot(X, Y)
                if R >= 179.9 or np.all(d <= R):
                    xs.append(la)
                    ys.append(lo)
                    continue
                if X.min() > R or X.max() < -R or Y.min() > R or Y.max() < -R:
                    continue
                for t in th:
                    X, Y = _clip_half(X, Y, math.sin(t), math.cos(t), R * math.cos(math.pi / n))
                    if X.size < 3:
                        break
                if X.size < 3:
                    continue
                d = np.hypot(X, Y)
                rim = d >= R * math.cos(math.pi / n) * (1 - 1e-9)
                X, Y = _densify(X, Y, rim & np.roll(rim, -1), R)
                la2, lo2 = inv(X, Y)
                xs.append(la2)
                ys.append(lo2)
        else:
            la0, la1 = self.latlim
            if self.name == 'ups':
                lo0, lo1 = -180.0, 180.0
            else:
                lo0, lo1 = self.lonlim[0] - o_lon, self.lonlim[1] - o_lon
            eps = 1e-7
            for la, lo in _rings(lat, lon):
                dl = np.rad2deg(np.unwrap(np.deg2rad(lo - o_lon)))
                if abs(dl[-1] - dl[0]) > 180:
                    pole = -90.0 if la.mean() < 0 else 90.0
                    dl, la = np.append(dl, [dl[-1], dl[0]]), np.append(la, [pole, pole])
                for k in range(math.floor((lo0 - dl.max()) / 360), math.ceil((lo1 - dl.min()) / 360) + 1):
                    X, Y = dl + 360 * k, la
                    for a, b, c in ((1, 0, lo1 - eps), (-1, 0, -(lo0 + eps)), (0, 1, la1 - eps), (0, -1, -(la0 + eps))):
                        X, Y = _clip_half(X, Y, a, b, c)
                        if X.size < 3:
                            break
                    if X.size < 3:
                        continue
                    cut = np.zeros(X.size, bool)
                    for v, lim in ((X, lo0 + eps), (X, lo1 - eps), (Y, la0 + eps), (Y, la1 - eps)):
                        on = np.abs(v - lim) < 1e-9
                        cut |= on & np.roll(on, -1)
                    X, Y = _densify(X, Y, cut)
                    xs.append(Y)
                    ys.append(X + o_lon)
        if not xs:
            return np.zeros(0), np.zeros(0)
        la = np.concatenate([np.append(a, np.nan) for a in xs])
        lo = np.concatenate([np.append(b, np.nan) for b in ys])
        ok = np.isfinite(la)
        x, y = self.proj.fwd(np.where(ok, la, 0.0), np.where(ok, lo, 0.0))
        return np.where(ok, x, np.nan), np.where(ok, y, np.nan)

    def frame_line(self):
        if self.name in _AZI and self.name != 'ups':
            az = np.linspace(0, 2 * math.pi, 361)
            la, lo = M.gc_direct(np.full(az.size, self.origin[0]), np.full(az.size, self.origin[1]), np.full(az.size, (self.frame_radius - 1e-6) * D2R), az)
            x, y = self.proj.fwd(la, lo)
            return np.asarray(x), np.asarray(y)
        la0, la1 = self.latlim
        lo0, lo1 = self.origin[1] + (self.lonlim[0] - self.origin[1]), self.origin[1] + (self.lonlim[1] - self.origin[1])
        n = 181
        eps = 1e-7
        lats = np.concatenate([np.full(n, la0), np.linspace(la0, la1, n), np.full(n, la1), np.linspace(la1, la0, n)])
        lons = np.concatenate([np.linspace(lo0 + eps, lo1 - eps, n), np.full(n, lo1 - eps), np.linspace(lo1 - eps, lo0 + eps, n), np.full(n, lo0 + eps)])
        x, y = self.proj.fwd(lats, lons)
        return np.asarray(x), np.asarray(y)


def _map_of(ax, fn=None):
    st = MAPS.get(ax.id) if ax is not None else None
    if st is None and fn:
        raise err('map:validate:expectedMapAxes', f'The current axes is not a map axes: make one with axesm or worldmap before {fn}.', fn)
    return st


def _cur_axes():
    from .graphics import gca_
    return gca_()


_PROPS = {'mapprojection': 'name', 'maplatlimit': 'latlim', 'maplonlimit': 'lonlim', 'origin': 'origin', 'mapparallels': 'parallels',
          'falseeasting': 'fe', 'falsenorthing': 'fn', 'scalefactor': 'k0', 'zone': 'zone', 'frame': 'frame', 'grid': 'grid',
          'meridianlabel': 'mlabel', 'parallellabel': 'plabel', 'mlinelocation': 'mline', 'plinelocation': 'pline',
          'mlabellocation': 'mlabelloc', 'plabellocation': 'plabelloc', 'mlabelparallel': 'mlabelparallel', 'plabelmeridian': 'plabelmeridian',
          'gcolor': 'gcolor', 'glinestyle': 'glinestyle', 'glinewidth': 'glinewidth', 'fedgecolor': 'fedgecolor', 'ffacecolor': 'ffacecolor',
          'flinewidth': 'flinewidth', 'fontsize': 'fontsize', 'geoid': 'geoid', 'flatlimit': 'flatlim'}


def _apply_props(st, pairs, fn):
    from ..graphics_base import to_color
    for k, v in pairs:
        key = k.lower()
        if key not in _PROPS:
            raise err('map:setm:unknownProperty', f"'{k}' is not a map axes property known here.", fn)
        attr = _PROPS[key]
        if attr in ('frame', 'grid', 'mlabel', 'plabel'):
            s = opt_str(v)
            setattr(st, attr, (s.lower() == 'on') if s is not None else bool(num(v)))
        elif attr in ('latlim', 'lonlim'):
            setattr(st, attr, [float(x) for x in darr(v).reshape(-1)[:2]])
        elif attr == 'origin':
            o = [float(x) for x in darr(v).reshape(-1)]
            st.origin = (o + [0.0, 0.0, 0.0])[:3]
        elif attr == 'parallels':
            p = darr(v).reshape(-1)
            st.parallels = [float(x) for x in p] if p.size else None
        elif attr == 'name':
            nm = py_str(v).lower()
            if nm not in M.PROJECTIONS:
                raise err('map:axesm:unknownProjection', f"'{nm}' is not a projection known here: {', '.join(sorted(M.PROJECTIONS))}.", fn)
            st.name = nm
        elif attr == 'zone':
            st.zone = py_str(v).upper()
            z = int(''.join(c for c in st.zone if c.isdigit()) or 31)
            band = st.zone[-1] if st.zone and st.zone[-1].isalpha() else 'N'
            st.origin = [0.0, -183.0 + 6 * z, 0.0]
            st.lonlim = [-183.0 + 6 * z - 3, -183.0 + 6 * z + 3]
            st.latlim = [0.0, 84.0] if band >= 'N' else [-80.0, 0.0]
            st.fn = 0.0 if band >= 'N' else 10000000.0 * (st.geoid[0] / 6378137.0 if st.geoid[0] > 1000 else 0.0)
        elif attr == 'geoid':
            st.geoid = _ellipsoid(v, fn)
        elif attr in ('gcolor', 'fedgecolor'):
            setattr(st, attr, to_color(v))
        elif attr == 'ffacecolor':
            st.ffacecolor = to_color(v, ('none',))
        elif attr in ('glinestyle', 'mlabelparallel', 'plabelmeridian'):
            setattr(st, attr, py_str(v).lower())
        elif attr == 'flatlim':
            f = darr(v).reshape(-1)
            if st.name in _AZI and f.size == 2:
                st.frame_radius = float(f[1])
        else:
            setattr(st, attr, float(num(v)))


def _pairs(args, fn):
    if len(args) % 2:
        raise err('map:validate:pairs', 'Properties must come in name-value pairs.', fn)
    return [(sval(args[i], 'property', fn), args[i + 1]) for i in range(0, len(args), 2)]


def _draw_map(ax, st, tight=False):
    """The frame, graticule and labels, made again; the limits set to the frame."""
    from .graphics import plot as plot_fn
    for c in list(ax.children):
        if c.valid and c.props.get('Tag') in ('Frame', 'Graticule', 'MLabel', 'PLabel'):
            c.delete_handle()
    fx, fy = st.frame_line()
    fx, fy = np.asarray(fx, float), np.asarray(fy, float)
    ok = np.isfinite(fx) & np.isfinite(fy)
    if st.frame:
        if st.ffacecolor != 'none':
            p = REG['patch'].fn(1, out(fx[ok].reshape(-1, 1)), out(fy[ok].reshape(-1, 1)), np.array([list(st.ffacecolor)]))
            p.props['Tag'] = 'Frame'
            p.props['EdgeColor'] = st.fedgecolor
            p.props['LineWidth'] = st.flinewidth
        else:
            h = REG['line'].fn(1, out(fx.reshape(1, -1)), out(fy.reshape(1, -1)))
            h.props.update({'Color': st.fedgecolor, 'LineWidth': st.flinewidth, 'Tag': 'Frame'})
    if st.grid:
        xs, ys = [], []
        lo_start = math.ceil((st.lonlim[0] if st.name not in _AZI else -180) / st.mline) * st.mline
        lo_end = st.lonlim[1] if st.name not in _AZI else 180 - 1e-9
        la_rng = (st.latlim[0], st.latlim[1]) if st.name not in _AZI else (-90.0, 90.0)
        for lo in np.arange(lo_start, lo_end + 1e-9, st.mline):
            la = np.linspace(max(la_rng[0], -89.0 if st.name == 'mercator' else -90.0), min(la_rng[1], 89.0 if st.name == 'mercator' else 90.0), 181)
            x, y = st.project(la, np.full(la.size, lo), cut=False)
            xs += list(x) + [np.nan]
            ys += list(y) + [np.nan]
        for la in np.arange(math.ceil(la_rng[0] / st.pline) * st.pline, la_rng[1] + 1e-9, st.pline):
            if abs(la) >= 90:
                continue
            lo = np.linspace(st.lonlim[0], st.lonlim[1], 361) if st.name not in _AZI else np.linspace(-180, 180, 361)
            x, y = st.project(np.full(lo.size, la), lo, cut=st.name not in _AZI)
            xs += list(x) + [np.nan]
            ys += list(y) + [np.nan]
        if xs:
            h = REG['line'].fn(1, out(np.array([xs], float)), out(np.array([ys], float)))
            h.props.update({'Color': st.gcolor, 'LineStyle': st.glinestyle, 'LineWidth': st.glinewidth, 'Tag': 'Graticule'})
    if st.mlabel and st.name not in _AZI:
        lat_at = st.latlim[0] if st.mlabelparallel == 'south' else st.latlim[1]
        step = st.mlabelloc or st.mline
        for lo in np.arange(math.ceil(st.lonlim[0] / step) * step, st.lonlim[1] + 1e-9, step):
            x, y = st.proj.fwd(lat_at, lo)
            if np.isfinite(x) and np.isfinite(y):
                lon_w = (lo + 180) % 360 - 180
                txt = f"{abs(lon_w):g}°{'' if lon_w in (0, 180, -180) else ('E' if lon_w > 0 else 'W')}"
                t = REG['text'].fn(1, float(x), float(y), Char.of(txt))
                t.props.update({'HorizontalAlignment': 'center', 'VerticalAlignment': 'top' if st.mlabelparallel == 'south' else 'bottom',
                                'FontSize': st.fontsize, 'Tag': 'MLabel', 'Clipping': False})
    if st.plabel and st.name not in _AZI:
        lon_at = st.lonlim[0] if st.plabelmeridian == 'west' else st.lonlim[1]
        step = st.plabelloc or st.pline
        for la in np.arange(math.ceil(st.latlim[0] / step) * step, st.latlim[1] + 1e-9, step):
            if abs(la) >= 90:
                continue
            x, y = st.proj.fwd(la, lon_at + (1e-7 if st.plabelmeridian == 'west' else -1e-7))
            if np.isfinite(x) and np.isfinite(y):
                txt = f"{abs(la):g}°{'' if la == 0 else ('N' if la > 0 else 'S')}  " if st.plabelmeridian == 'west' else f"  {abs(la):g}°{'' if la == 0 else ('N' if la > 0 else 'S')}"
                t = REG['text'].fn(1, float(x), float(y), Char.of(txt))
                t.props.update({'HorizontalAlignment': 'right' if st.plabelmeridian == 'west' else 'left', 'VerticalAlignment': 'middle',
                                'FontSize': st.fontsize, 'Tag': 'PLabel', 'Clipping': False})
    # the limits: the frame's extent
    if ok.any():
        x0, x1, y0, y1 = np.nanmin(fx[ok]), np.nanmax(fx[ok]), np.nanmin(fy[ok]), np.nanmax(fy[ok])
        pad = 0.0 if tight else 0.02
        dx, dy = (x1 - x0) or 1.0, (y1 - y0) or 1.0
        ax.set_value('XLim', np.array([[x0 - pad * dx, x1 + pad * dx]]))
        ax.set_value('YLim', np.array([[y0 - pad * dy, y1 + pad * dy]]))
    ax.touch()


def _new_map_axes(st):
    from .graphics import newplot, set_current_axes
    ax = newplot(None)
    for c in list(ax.children):
        c.delete_handle()
    ax.props['Visible'] = False
    ax.props['DataAspectRatio'] = np.array([[1.0, 1.0, 1.0]])
    ax.props['DataAspectRatioMode'] = 'manual'
    ax.props['NextPlot'] = 'add'
    ax.props['Box'] = False
    MAPS[ax.id] = st
    set_current_axes(ax)
    return ax


@bi('axesm', arr=False)
def axesm(nargout, *args):
    args = list(args)
    name = 'eqdcylin'
    if args and len(args) % 2 == 1:
        name = py_str(args.pop(0)).lower()
    pairs = _pairs(args, 'axesm')
    proj_pair = next((v for k, v in pairs if k.lower() == 'mapprojection'), None)
    if proj_pair is not None:
        name = py_str(proj_pair).lower()
    if name not in M.PROJECTIONS:
        raise err('map:axesm:unknownProjection', f"'{name}' is not a projection known here: {', '.join(sorted(M.PROJECTIONS))}.", 'axesm')
    st = MapState(name)
    if name == 'mercator':
        st.latlim = [-86.0, 86.0]
    if name in _CONIC:
        st.latlim = [0.0, 90.0]
    if name == 'utm':
        _apply_props(st, [('Zone', Char.of('31N'))], 'axesm')
    if name == 'ups':
        st.latlim = [60.0, 90.0]
    _apply_props(st, [p for p in pairs if p[0].lower() != 'mapprojection'], 'axesm')
    if any(k.lower() == 'origin' for k, _ in pairs) and not any(k.lower() == 'maplonlimit' for k, _ in pairs) and name not in ('utm',):
        st.lonlim = [st.origin[1] - 180.0, st.origin[1] + 180.0]
    if any(k.lower() == 'maplonlimit' for k, _ in pairs) and not any(k.lower() == 'origin' for k, _ in pairs) and name not in _AZI:
        st.origin[1] = (st.lonlim[0] + st.lonlim[1]) / 2
    if name in _AZI and not any(k.lower() == 'origin' for k, _ in pairs) and any(k.lower() == 'maplatlimit' for k, _ in pairs):
        st.origin = [90.0 if st.latlim[1] >= 90 else -90.0 if st.latlim[0] <= -90 else (st.latlim[0] + st.latlim[1]) / 2, st.origin[1], 0.0]
        if st.latlim[1] >= 90 or st.latlim[0] <= -90:
            st.frame_radius = 90.0 - (st.latlim[0] if st.latlim[1] >= 90 else -st.latlim[1])
    st.setup()
    ax = _new_map_axes(st)
    _draw_map(ax, st)
    return ax if nargout else None


_REGIONS = {'world': ([-90, 90], [-180, 180]), 'europe': ([34, 72], [-25, 45]), 'africa': ([-36, 38], [-20, 55]),
            'asia': ([-10, 80], [25, 180]), 'north america': ([7, 84], [-170, -50]), 'south america': ([-57, 13], [-82, -34]),
            'australia': ([-45, -10], [110, 155]), 'antarctica': ([-90, -60], [-180, 180]), 'arctic': ([60, 90], [-180, 180]),
            'sweden': ([55, 70], [10, 25]), 'scandinavia': ([54, 72], [4, 32]), 'nordic': ([54, 72], [-25, 32])}


@bi('worldmap', arr=False)
def worldmap(nargout, *args):
    if not args:
        latlim, lonlim = _REGIONS['world']
    elif len(args) == 1 and is_str(args[0]):
        key = py_str(args[0]).lower()
        if key not in _REGIONS:
            raise err('map:worldmap:unknownRegion', f"'{py_str(args[0])}' is not a region known here: {', '.join(sorted(_REGIONS))}.", 'worldmap')
        latlim, lonlim = _REGIONS[key]
    else:
        if len(args) != 2 or numel(args[0]) != 2 or numel(args[1]) != 2:
            raise err('map:worldmap:limits', 'Give a region name, or latlim and lonlim of two elements each.', 'worldmap')
        latlim = [float(x) for x in darr(args[0]).reshape(-1)]
        lonlim = [float(x) for x in darr(args[1]).reshape(-1)]
    latlim, lonlim = list(map(float, latlim)), list(map(float, lonlim))
    span_lat = latlim[1] - latlim[0]
    span_lon = (lonlim[1] - lonlim[0]) % 360 or 360.0
    lon0 = lonlim[0] + span_lon / 2
    if span_lat >= 150 and span_lon >= 300:
        pairs = [('MapProjection', Char.of('robinson')), ('Origin', np.array([[0.0, 0.0, 0.0]]))]
        st_lat, st_lon = [-90.0, 90.0], [-180.0, 180.0]
        name = 'robinson'
    elif latlim[1] >= 89.9 or latlim[0] <= -89.9:
        name = 'stereo'
        north = latlim[1] >= 89.9
        st_lat, st_lon = latlim, [-180.0, 180.0]
    elif span_lon > 1.5 * span_lat and span_lat > 20:
        name = 'eqdconic'
        st_lat, st_lon = latlim, [lonlim[0], lonlim[0] + span_lon]
    else:
        name = 'eqdconic' if span_lat > 10 else 'tranmerc'
        st_lat, st_lon = latlim, [lonlim[0], lonlim[0] + span_lon]
    st = MapState(name)
    st.latlim, st.lonlim = list(st_lat), list(st_lon)
    if name == 'stereo':
        north = latlim[1] >= 89.9
        st.origin = [90.0 if north else -90.0, 0.0, 0.0]
        st.frame_radius = 90.0 - (latlim[0] if north else -latlim[1])
    elif name != 'robinson':
        st.origin = [(latlim[0] + latlim[1]) / 2 if name == 'tranmerc' else 0.0, lon0, 0.0]
    st.frame = st.grid = st.mlabel = st.plabel = name not in _AZI or True
    step = _nice_step(max(span_lat, span_lon / 2))
    st.mline = st.pline = step
    if name == 'robinson':
        st.mline, st.pline = 30.0, 30.0
    st.setup()
    ax = _new_map_axes(st)
    if name in _AZI:
        st.mlabel = st.plabel = False
    _draw_map(ax, st)
    return ax if nargout else None


def _nice_step(span):
    for s in (1, 2, 5, 10, 15, 20, 30, 45, 60):
        if span / s <= 6:
            return float(s)
    return 90.0


@bi('setm', arr=False)
def setm(nargout, *args):
    ax = args[0] if args and getattr(args[0], 'TYPE', None) == 'axes' else _cur_axes()
    rest = args[1:] if args and getattr(args[0], 'TYPE', None) == 'axes' else args
    st = _map_of(ax, 'setm')
    pairs = _pairs(rest, 'setm')
    _apply_props(st, pairs, 'setm')
    st.setup()
    _draw_map(ax, st)
    return None


def _state_struct(st):
    from ..graphics_base import color_value
    col = lambda c: color_value(c) if not isinstance(c, str) else Char.of(c)
    return Struct.scalar({
        'mapprojection': Char.of(st.name), 'zone': Char.of(st.zone), 'angleunits': Char.of('degrees'), 'aspect': Char.of('normal'),
        'falsenorthing': st.fn, 'falseeasting': st.fe, 'geoid': np.array([[st.geoid[0], st.geoid[1]]]),
        'maplatlimit': np.array([st.latlim]), 'maplonlimit': np.array([st.lonlim]),
        'mapparallels': np.array([st.proj.parallels or []], float) if st.proj.parallels else np.zeros((1, 0)),
        'origin': np.array([st.origin]), 'scalefactor': st.k0, 'frame': Char.of('on' if st.frame else 'off'),
        'grid': Char.of('on' if st.grid else 'off'), 'meridianlabel': Char.of('on' if st.mlabel else 'off'),
        'parallellabel': Char.of('on' if st.plabel else 'off'), 'mlinelocation': st.mline, 'plinelocation': st.pline,
        'gcolor': col(st.gcolor), 'glinestyle': Char.of(st.glinestyle), 'glinewidth': st.glinewidth, 'fedgecolor': col(st.fedgecolor),
        'ffacecolor': col(st.ffacecolor), 'flinewidth': st.flinewidth, 'fontsize': st.fontsize})


def _mstruct_to_state(s):
    st = MapState(py_str(s.get1('mapprojection')) if 'mapprojection' in s.f else 'eqdcylin')
    pairs = []
    for k in s.f:
        if k.lower() in _PROPS and k.lower() != 'mapprojection':
            v = s.get1(k)
            if type(v) is np.ndarray and v.size == 0:
                continue
            pairs.append((k, v))
    _apply_props(st, pairs, 'projfwd')
    st.setup()

    class _P:
        def fwd(self, lat, lon):
            return st.proj.fwd(lat, lon)

        def inv(self, x, y):
            return st.proj.inv(x, y)
    return _P()


@bi('gcm', arr=False)
def gcm(nargout, *args):
    ax = args[0] if args else _cur_axes()
    if getattr(ax, 'TYPE', None) != 'axes':
        raise err('map:gcm:notAxes', 'gcm takes the handle of map axes.', 'gcm')
    return _state_struct(_map_of(ax, 'gcm'))


@bi('getm', arr=False)
def getm(nargout, *args):
    ax = args[0] if args and getattr(args[0], 'TYPE', None) == 'axes' else _cur_axes()
    name = py_str(args[-1]).lower()
    s = _state_struct(_map_of(ax, 'getm'))
    if name not in s.f:
        raise err('map:getm:unknownProperty', f"'{name}' is not a map axes property known here.", 'getm')
    return s.get1(name)


@bi('defaultm', arr=False)
def defaultm(nargout, *args):
    v = args[0] if args else Char.of('eqdcylin')
    if type(v) is Struct:
        return v
    name = py_str(v).lower()
    if name not in M.PROJECTIONS:
        raise err('map:defaultm:unknownProjection', f"'{py_str(v)}' is not a projection known here.", 'defaultm')
    st = MapState(name)
    return _state_struct(st)


@bi('ismap')
def ismap(nargout, *args):
    ax = args[0] if args else _cur_axes()
    return getattr(ax, 'id', None) in MAPS


def _onoff_map(attr, fn):
    def f(nargout, *args):
        ax = _cur_axes()
        st = _map_of(ax, fn)
        if args and opt_str(args[0]) is not None and opt_lower(args[0]) in ('on', 'off', 'toggle', 'reset'):
            w = opt_lower(args[0])
            setattr(st, attr, (not getattr(st, attr)) if w == 'toggle' else w == 'on')
            rest = args[1:]
        elif args:
            rest = args
            setattr(st, attr, True)
        else:
            setattr(st, attr, not getattr(st, attr))
            rest = ()
        if rest:
            _apply_props(st, _pairs(rest, fn), fn)
            st.setup()
        _draw_map(ax, st)
        return None
    return f


bi('framem', arr=False)(_onoff_map('frame', 'framem'))
bi('gridm', arr=False)(_onoff_map('grid', 'gridm'))
bi('mlabel', arr=False)(_onoff_map('mlabel', 'mlabel'))
bi('plabel', arr=False)(_onoff_map('plabel', 'plabel'))


@bi('tightmap', arr=False)
def tightmap(nargout, *args):
    ax = _cur_axes()
    st = _map_of(ax, 'tightmap')
    _draw_map(ax, st, tight=True)
    return None


@bi('showaxes', arr=False)
def showaxes(nargout, *args):
    ax = _cur_axes()
    w = opt_lower(args[0]) if args and opt_str(args[0]) is not None else 'on'
    ax.props['Visible'] = w in ('on', 'show')
    ax.touch()
    return None


def _proj_xy(ax, lat, lon, fn):
    st = MAPS.get(ax.id)
    lat, lon = darr(lat), darr(lon)
    if st is None:
        # not a map axes: longitude as x, latitude as y
        return lon.astype(float), lat.astype(float), None
    if lat.ndim == 2 and lat.shape[0] > 1 and lat.shape[1] > 1:
        xs, ys = [], []
        for j in range(lat.shape[1]):
            x, y = st.project(lat[:, j], lon[:, j] if lon.shape == lat.shape else lon.reshape(-1))
            xs.append(x)
            ys.append(y)
        n = max(len(x) for x in xs)
        X = np.full((n, len(xs)), np.nan)
        Y = np.full((n, len(xs)), np.nan)
        for j, (x, y) in enumerate(zip(xs, ys)):
            X[:len(x), j], Y[:len(y), j] = x, y
        return X, Y, st
    x, y = st.project(lat.reshape(-1), lon.reshape(-1))
    shape = (1, -1) if lat.shape[0] == 1 else (-1, 1)
    return x.reshape(shape), y.reshape(shape), st


@bi('mfwdtran', nout=2)
def mfwdtran(nargout, *args):
    if type(args[0]) is Struct:
        p = _mstruct_to_state(args[0])
        x, y = p.fwd(darr(args[1]), darr(args[2]))
    else:
        st = _map_of(_cur_axes(), 'mfwdtran')
        x, y = st.proj.fwd(darr(args[0]), darr(args[1]))
    return (out(np.asarray(x)), out(np.asarray(y))) if nargout > 1 else out(np.asarray(x))


@bi('minvtran', nout=2)
def minvtran(nargout, *args):
    if type(args[0]) is Struct:
        p = _mstruct_to_state(args[0])
        la, lo = p.inv(darr(args[1]), darr(args[2]))
    else:
        st = _map_of(_cur_axes(), 'minvtran')
        la, lo = st.proj.inv(darr(args[0]), darr(args[1]))
    # NaN in, NaN out (a polar projection's inverse makes NaN its pole)
    bad = ~(np.isfinite(darr(args[-2])) & np.isfinite(darr(args[-1])))
    la, lo = np.where(bad, np.nan, la), np.where(bad, np.nan, lo)
    return (out(np.asarray(la)), out(np.asarray(lo))) if nargout > 1 else out(np.asarray(la))


def _latlon_args(args, fn):
    args = list(args)
    if args and type(args[0]) is np.ndarray and args[0].ndim == 2 and args[0].shape[1] == 2 and (len(args) == 1 or not isinstance(args[1], np.ndarray) or opt_str(args[1]) is not None):
        m = args.pop(0)
        return m[:, 0:1], m[:, 1:2], args
    return args[0], args[1], args[2:]


@bi('plotm', arr=False)
def plotm(nargout, *args):
    ax = _cur_axes()
    _map_of(ax, 'plotm')
    lat, lon, rest = _latlon_args(args, 'plotm')
    x, y, st = _proj_xy(ax, lat, lon, 'plotm')
    h = REG['plot'].fn(1, out(x), out(y), *rest)
    return h if nargout else None


@bi('linem', arr=False)
def linem(nargout, *args):
    ax = _cur_axes()
    _map_of(ax, 'linem')
    lat, lon, rest = _latlon_args(args, 'linem')
    x, y, st = _proj_xy(ax, lat, lon, 'linem')
    h = REG['line'].fn(1, out(x), out(y), *rest)
    return h if nargout else None


@bi('scatterm', arr=False)
def scatterm(nargout, *args):
    ax = _cur_axes()
    _map_of(ax, 'scatterm')
    lat, lon = darr(args[0]).reshape(-1), darr(args[1]).reshape(-1)
    st = MAPS[ax.id]
    x, y = st.proj.fwd(lat, lon)
    keep = np.isfinite(st.project(lat, lon, cut=False)[0])
    x, y = np.where(keep, x, np.nan), np.where(keep, y, np.nan)
    h = REG['scatter'].fn(1, out(np.asarray(x).reshape(-1, 1)), out(np.asarray(y).reshape(-1, 1)), *args[2:])
    return h if nargout else None


@bi('textm', arr=False)
def textm(nargout, *args):
    ax = _cur_axes()
    st = _map_of(ax, 'textm')
    lat, lon = darr(args[0]).reshape(-1), darr(args[1]).reshape(-1)
    x, y = st.proj.fwd(lat, lon)
    rest = list(args[2:])
    if rest and not is_str(rest[0]) and type(rest[0]) is not Cell:
        rest = rest[1:]          # textm(lat, lon, z, string)
    h = REG['text'].fn(1, out(np.asarray(x, float).reshape(-1, 1)), out(np.asarray(y, float).reshape(-1, 1)), *rest)
    return h if nargout else None


@bi('patchm', 'fillm', arr=False)
def patchm(nargout, *args):
    ax = _cur_axes()
    st = _map_of(ax, 'patchm')
    lat, lon = darr(args[0]).reshape(-1), darr(args[1]).reshape(-1)
    x, y = st.project_polygon(lat, lon)
    rest = list(args[2:])
    if not rest or not (is_str(rest[0]) or numel(rest[0]) == 3):
        rest = [np.array([[0.95, 0.9, 0.6]])] + rest
    h = REG['patch'].fn(1, out(x.reshape(-1, 1)), out(y.reshape(-1, 1)), *rest)
    h.rings = True
    return h if nargout else None


def _grid_xy(st, lat, lon):
    lat, lon = darr(lat), darr(lon)
    if lat.ndim == 2 and min(lat.shape) == 1 and lon.ndim == 2 and min(lon.shape) == 1 and lat.size != lon.size or (lat.shape != lon.shape):
        LO, LA = np.meshgrid(lon.reshape(-1), lat.reshape(-1))
    else:
        LA, LO = lat, lon
    if st is None:
        return LO, LA
    x, y = st.proj.fwd(LA, LO)
    keep = np.isfinite(st.project(LA.reshape(-1), LO.reshape(-1), cut=False)[0]).reshape(LA.shape)
    return np.where(keep, x, np.nan), np.where(keep, y, np.nan)


@bi('surfm', 'pcolorm', arr=False)
def surfm(nargout, *args):
    ax = _cur_axes()
    st = _map_of(ax, 'surfm')
    lat, lon, Z = args[0], args[1], darr(args[2])
    X, Y = _grid_xy(st, lat, lon)
    h = REG['surface'].fn(1, out(X), out(Y), np.zeros(Z.shape), out(Z), *args[3:])
    h.props['EdgeColor'] = 'none'
    h.props['FaceColor'] = 'flat'
    ax.touch()
    return h if nargout else None


@bi('contourm', nout=2, arr=False)
def contourm(nargout, *args):
    ax = _cur_axes()
    st = MAPS.get(ax.id)
    args = list(args)
    if isinstance(args[1], RasterRef):
        Z = darr(args[0])
        R_ = args[1]
        lat, lon = R_.grid_latlon(Z.shape)
        rest = args[2:]
    else:
        if len(args) < 3:
            raise err('MATLAB:minrhs', 'Give lat, lon and Z, or Z and its raster reference.', 'contourm')
        lat, lon, Z = darr(args[0]), darr(args[1]), darr(args[2])
        rest = args[3:]
    if lat.shape != Z.shape:
        LO, LA = np.meshgrid(lon.reshape(-1), lat.reshape(-1))
    else:
        LA, LO = lat, lon
    lev = []
    if rest and not is_str(rest[0]):
        lev = [rest.pop(0)]
    C = darr(REG['contourc'].fn(1, out(LO[0, :].reshape(1, -1)) if LO.ndim == 2 else out(LO), out(LA[:, 0].reshape(-1, 1)), out(Z), *lev))
    xs, ys = [], []
    k = 0
    levels = []
    while k < C.shape[1]:
        L, n = C[0, k], int(C[1, k])
        lo_, la_ = C[0, k + 1:k + 1 + n], C[1, k + 1:k + 1 + n]
        if st is not None:
            x, y = st.project(la_, lo_)
        else:
            x, y = lo_, la_
        xs += list(x) + [np.nan]
        ys += list(y) + [np.nan]
        levels.append(L)
        k += n + 1
    h = REG['line'].fn(1, out(np.array([xs], float)), out(np.array([ys], float)), *rest)
    return (out(C), h) if nargout > 1 else (out(C) if nargout else None)


# ---- geoshow and mapshow ---------------------------------------------------------------------------------------------------

def _style(args):
    """DisplayType and the other name-value pairs."""
    kind = None
    pairs = []
    i = 0
    while i + 1 < len(args):
        k = sval(args[i], 'property', 'geoshow')
        if k.lower() == 'displaytype':
            kind = py_str(args[i + 1]).lower()
        else:
            pairs.append((k, args[i + 1]))
        i += 2
    return kind, pairs


def _show(kind, x, y, pairs, polygon_color=(0.95, 0.9, 0.6)):
    from ..graphics_base import to_color
    flat = [v for kv in pairs for v in kv]
    names = {k.lower(): v for k, v in pairs}
    if kind == 'point':
        h = REG['line'].fn(1, out(np.asarray(x, float).reshape(1, -1)), out(np.asarray(y, float).reshape(1, -1)))
        h.props.update({'LineStyle': 'none', 'Marker': '+', 'Color': (1.0, 0.0, 0.0)})
    elif kind == 'polygon':
        # one patch a feature: its rings parted by NaN, filled even-odd, so that a hole stays open
        x, y = np.asarray(x, float).reshape(-1), np.asarray(y, float).reshape(-1)
        if not np.any(np.isfinite(x) & np.isfinite(y)):
            return None
        fc = to_color(names['facecolor'], ('none', 'flat')) if 'facecolor' in names else polygon_color
        h = REG['patch'].fn(1, out(x.reshape(-1, 1)), out(y.reshape(-1, 1)), np.array([list(fc)]) if not isinstance(fc, str) else Char.of(fc))
        h.rings = True
        h.props['EdgeColor'] = (0.0, 0.0, 0.0)
        for k, v in pairs:
            if k.lower() != 'facecolor':
                REG['set'].fn(0, h, Char.of(k), v)
        return h
    else:
        h = REG['line'].fn(1, out(np.asarray(x, float).reshape(1, -1)), out(np.asarray(y, float).reshape(1, -1)))
        h.props['Color'] = (0.0, 0.447, 0.741)
    for k, v in pairs:
        REG['set'].fn(0, h, Char.of(k), v)
    return h


def _sget(s, k, i):
    """Field k of element i (linear, in column order) of a struct array."""
    return s.f[k].reshape(-1, order='F')[i]


def _feature_kind(s, i):
    g = py_str(_sget(s, 'Geometry', i)).lower() if 'Geometry' in s.f else 'line'
    return {'point': 'point', 'multipoint': 'point', 'line': 'line', 'polyline': 'line', 'polygon': 'polygon'}.get(g, 'line')


@bi('geoshow', aw=True, arr=False)
async def geoshow(nargout, *args):
    from .graphics import newplot
    ax = _cur_axes() if R_has_axes() else None
    if ax is None or ax.id not in MAPS:
        ax = newplot(None)
        ax.props['DataAspectRatio'] = np.array([[1.0, 1.0, 1.0]])
        ax.props['DataAspectRatioMode'] = 'manual'
        ax.props['NextPlot'] = 'add'
    args = list(args)
    st = MAPS.get(ax.id)
    if args and is_str(args[0]) and (py_str(args[0]).lower().endswith(('.shp', '.tif', '.tiff')) or GD.dataset(py_str(args[0]), 'shp')):
        fname = py_str(args.pop(0))
        if not fname.lower().endswith(('.tif', '.tiff')):
            args = [await shaperead(1, Char.of(fname), Char.of('UseGeoCoords'), True)] + args
        else:
            A, Rr = await readgeoraster(2, Char.of(fname))
            args = [A, Rr] + args
    if args and type(args[0]) is Struct:
        S = args[0]
        kind_given, pairs = _style(args[1:])
        hs = []
        for i in range(S.size):
            la = darr(_sget(S, 'Lat', i) if 'Lat' in S.f else _sget(S, 'Y', i)).reshape(-1)
            lo = darr(_sget(S, 'Lon', i) if 'Lon' in S.f else _sget(S, 'X', i)).reshape(-1)
            kind = kind_given or _feature_kind(S, i)
            x, y = ((st.project_polygon(la, lo) if kind == 'polygon' else st.project(la, lo)) if st is not None else (lo, la))
            hs.append(_show(kind, x, y, pairs))
        hs = [h for h in hs if h is not None]
        ax.touch()
        return (hs[0] if len(hs) == 1 else _harr(hs)) if nargout else None
    if len(args) >= 2 and isinstance(args[1], RasterRef):
        Z, Rr = darr(args[0]), args[1]
        lat, lon = Rr.grid_latlon(Z.shape[:2])
        X, Y = _grid_xy(st, lat, lon)
        if Z.ndim == 3:
            h = REG['surface'].fn(1, out(X), out(Y), np.zeros(Z.shape[:2]), out(Z / (255.0 if Z.max() > 1 else 1.0)))
        else:
            h = REG['surface'].fn(1, out(X), out(Y), np.zeros(Z.shape), out(Z))
        h.props['EdgeColor'] = 'none'
        h.props['FaceColor'] = 'flat'
        ax.touch()
        return h if nargout else None
    if len(args) < 2 or is_str(args[1]):
        raise err('MATLAB:minrhs', 'Give lat and lon, a struct of shapes, a file name, or Z and its raster reference.', 'geoshow')
    lat, lon = darr(args[0]), darr(args[1])
    if lat.size != lon.size:
        raise err('map:geoshow:sizes', 'lat and lon must have the same number of elements.', 'geoshow')
    kind, pairs = _style(args[2:])
    if lat.ndim == 2 and min(lat.shape) > 1 and len(args) > 2 and not is_str(args[2]):
        Z = darr(args[2])
        X, Y = _grid_xy(st, lat, lon)
        h = REG['surface'].fn(1, out(X), out(Y), np.zeros(Z.shape), out(Z))
        h.props['EdgeColor'] = 'none'
        h.props['FaceColor'] = 'flat'
        ax.touch()
        return h if nargout else None
    if st is None:
        x, y = lon.reshape(-1), lat.reshape(-1)
    elif kind == 'polygon':
        x, y = st.project_polygon(lat.reshape(-1), lon.reshape(-1))
    else:
        x, y = st.project(lat.reshape(-1), lon.reshape(-1))
    h = _show(kind or 'line', x, y, pairs)
    ax.touch()
    return h if nargout else None


def R_has_axes():
    from ..graphics_base import STORE
    f = STORE.current
    return f is not None and f.valid and f.axes_list()


def _harr(hs):
    from ..graphics_base import HArr
    return HArr.of(hs)


@bi('mapshow', aw=True, arr=False)
async def mapshow(nargout, *args):
    from .graphics import newplot
    ax = newplot(None)
    ax.props['DataAspectRatio'] = np.array([[1.0, 1.0, 1.0]])
    ax.props['DataAspectRatioMode'] = 'manual'
    ax.props['NextPlot'] = 'add'
    args = list(args)
    if args and is_str(args[0]) and (py_str(args[0]).lower().endswith('.shp') or GD.dataset(py_str(args[0]), 'shp')):
        args = [await shaperead(1, args.pop(0))] + args
    if args and type(args[0]) is Struct:
        S = args[0]
        kind_given, pairs = _style(args[1:])
        hs = []
        for i in range(S.size):
            x = darr(_sget(S, 'X', i)).reshape(-1)
            y = darr(_sget(S, 'Y', i)).reshape(-1)
            hs.append(_show(kind_given or _feature_kind(S, i), x, y, pairs))
        hs = [h for h in hs if h is not None]
        ax.touch()
        return (hs[0] if len(hs) == 1 else _harr(hs)) if nargout else None
    if len(args) >= 2 and isinstance(args[1], RasterRef):
        Z, Rr = darr(args[0]), args[1]
        X, Y = Rr.grid_xy(Z.shape[:2])
        h = REG['surface'].fn(1, out(X), out(Y), np.zeros(Z.shape[:2]), out(Z if Z.ndim == 2 else Z / (255.0 if Z.max() > 1 else 1.0)))
        h.props['EdgeColor'] = 'none'
        h.props['FaceColor'] = 'flat'
        ax.touch()
        return h if nargout else None
    if len(args) < 2 or is_str(args[1]):
        raise err('MATLAB:minrhs', 'Give x and y, a struct of shapes, a file name, or Z and its raster reference.', 'mapshow')
    x, y = darr(args[0]).reshape(-1), darr(args[1]).reshape(-1)
    if x.size != y.size:
        raise err('map:mapshow:sizes', 'x and y must have the same number of elements.', 'mapshow')
    kind, pairs = _style(args[2:])
    h = _show(kind or 'line', x, y, pairs)
    ax.touch()
    return h if nargout else None


# ---- geographic axes ------------------------------------------------------------------------------------------------------------

def _geoaxes(ax=None, fresh_=False):
    """The current axes made geographic: longitude across, latitude up,
    degree ticks with their hemispheres, the aspect of the middle latitude."""
    from .graphics import newplot
    from ..graphics_base import Axes
    if ax is None:
        ax = newplot(None)
    if ax.kind != 'geo':
        ax.kind = 'geo'
        ax.props['Box'] = True
        ax.props['XGrid'] = True
        ax.props['YGrid'] = True
        ax.extra_geo = {'basemap': 'none'} if not hasattr(ax, 'extra_geo') else ax.extra_geo
    return ax


def _geo_aspect(ax):
    from ..glayout import auto_limits
    yl = ax.get_value('YLim').reshape(-1)
    mid = float(np.clip((yl[0] + yl[1]) / 2, -80, 80))
    ax.props['DataAspectRatio'] = np.array([[1.0, math.cos(mid * D2R), 1.0]])
    ax.props['DataAspectRatioMode'] = 'manual'


def _pop_basemap(args):
    """args without their Basemap name-value pair, and its value (or None)."""
    args = list(args)
    for i in range(len(args) - 1):
        if is_str(args[i]) and py_str(args[i]).lower() == 'basemap':
            return args[:i] + args[i + 2:], args[i + 1]
    return args, None


@bi('geoaxes', arr=False)
def geoaxes(nargout, *args):
    args, bm = _pop_basemap(args)
    ax = REG['axes'].fn(1, *args)
    _geoaxes(ax)
    if bm is not None:
        set_basemap(ax, bm)
    ax.props['XLim'] = np.array([[-180.0, 180.0]])
    ax.props['YLim'] = np.array([[-90.0, 90.0]])
    ax.props['XLimMode'] = ax.props['YLimMode'] = 'manual'
    _geo_aspect(ax)
    ax.touch()
    return ax if nargout else None


def _geo_target(args):
    from .graphics import split_axes_arg, newplot
    ax, rest = split_axes_arg(args)
    ax = newplot(ax)
    return ax, list(rest)


def _geo_finish(ax):
    # marked geographic after plotting: a plot that replaces resets the axes
    _geoaxes(ax)
    _geo_aspect(ax)
    ax.touch()


@bi('geoplot', arr=False)
def geoplot(nargout, *args):
    ax, rest = _geo_target(args)
    lat, lon = rest[0], rest[1]
    h = REG['plot'].fn(1, ax, lon, lat, *rest[2:])
    _geo_finish(ax)
    return h if nargout else None


@bi('geoscatter', arr=False)
def geoscatter(nargout, *args):
    ax, rest = _geo_target(args)
    lat, lon = rest[0], rest[1]
    h = REG['scatter'].fn(1, ax, lon, lat, *rest[2:])
    _geo_finish(ax)
    return h if nargout else None


@bi('geobubble', arr=False)
def geobubble(nargout, *args):
    args, bm = _pop_basemap(args)
    ax, rest = _geo_target(args)
    lat, lon = rest[0], rest[1]
    sz = rest[2] if len(rest) > 2 and not is_str(rest[2]) else 1.0
    extra = rest[3:] if len(rest) > 3 and not is_str(rest[2]) else rest[2:]
    if extra and not is_str(extra[0]):
        extra = [extra[0]] + list(extra[1:])
    h = REG['bubblechart'].fn(1, ax, lon, lat, sz, *extra)
    _geo_finish(ax)
    if bm is not None:
        set_basemap(ax, bm)
    return h if nargout else None


@bi('geolimits', nout=2, arr=False)
def geolimits(nargout, *args):
    from .graphics import split_axes_arg
    ax, rest = split_axes_arg(args)
    ax = ax or _cur_axes()
    _geoaxes(ax)
    if not rest:
        yl = ax.get_value('YLim').reshape(-1)
        xl = ax.get_value('XLim').reshape(-1)
        return (out(yl.reshape(1, -1)), out(xl.reshape(1, -1))) if nargout > 1 else out(yl.reshape(1, -1))
    if is_str(rest[0]):
        ax.props['XLimMode'] = ax.props['YLimMode'] = 'auto'
    else:
        ax.set_value('YLim', darr(rest[0]))
        ax.set_value('XLim', darr(rest[1]))
    _geo_finish(ax)
    return None


# ---- basemaps -------------------------------------------------------------------------------------------------------------
# The page draws them (pylab-basemap.js) and fetches their tiles only for
# axes that have one: none until a program names one.

BASEMAPS = ('streets', 'streets-light', 'streets-dark', 'satellite', 'topographic', 'landcover', 'colorterrain',
            'grayterrain', 'bluegreen', 'grayland', 'darkwater', 'none')
CUSTOM_BASEMAPS = {}          # addCustomBasemap: name -> the tiles' URL, attribution, deepest zoom level


def set_basemap(ax, value):
    name = sval(value, 'basemap name', 'geobasemap')
    # a new dict, not an update: a copy of the axes (copyobj) shares the old one
    if name.lower() in BASEMAPS:
        ax.extra_geo = dict(ax.extra_geo, basemap=name.lower(), custom=None)
    elif name in CUSTOM_BASEMAPS:
        ax.extra_geo = dict(ax.extra_geo, basemap=name, custom=dict(CUSTOM_BASEMAPS[name]))
    else:
        raise err('map:geobasemap:unknownBasemap', f"'{name}' is not a basemap: use one of {', '.join(BASEMAPS)}, or a name given to addCustomBasemap.", 'geobasemap')
    ax.touch()


@bi('geobasemap', arr=False)
def geobasemap(nargout, *args):
    from .graphics import split_axes_arg
    ax, rest = split_axes_arg(args)
    ax = ax or _cur_axes()
    _geoaxes(ax)
    if not rest:
        return Char.of(ax.extra_geo.get('basemap', 'none'))
    set_basemap(ax, rest[0])
    return None


@bi('addCustomBasemap', arr=False)
def addCustomBasemap(nargout, *args):
    if len(args) < 2:
        raise err('MATLAB:minrhs', 'addCustomBasemap takes a name and the URL of the tiles.', 'addCustomBasemap')
    name = sval(args[0], 'basemap name', 'addCustomBasemap')
    url = sval(args[1], 'URL', 'addCustomBasemap')
    if not name.strip() or name.lower() in BASEMAPS:
        raise err('map:basemap:reservedName', f"'{name}' is the name of a basemap already: give the new one a name of its own.", 'addCustomBasemap')
    tmpl = url.replace('${', '{')
    if not tmpl.lower().startswith(('https://', 'http://')) or not all(k in tmpl for k in ('{x}', '{y}', '{z}')):
        raise err('map:basemap:badURL', "The URL of a basemap's tiles starts with https:// and has ${x}, ${y} and ${z} in it, for the tile's column, row and zoom level.", 'addCustomBasemap')
    spec = {'url': tmpl, 'note': '', 'label': name, 'max': 18}
    for i in range(2, len(args) - 1, 2):
        k = sval(args[i], 'option', 'addCustomBasemap').lower()
        v = args[i + 1]
        if k == 'attribution':
            spec['note'] = ' '.join(py_str(x) for x in v.a.reshape(-1)) if type(v) is Cell else py_str(v)
        elif k == 'displayname':
            spec['label'] = py_str(v)
        elif k == 'maxzoomlevel':
            z = num(v)
            if not (0 <= z <= 25 and z == int(z)):
                raise err('map:basemap:badZoom', 'MaxZoomLevel is a whole number from 0 to 25.', 'addCustomBasemap')
            spec['max'] = int(z)
        elif k == 'isdeployable':
            pass
        else:
            raise err('map:basemap:badOption', f"addCustomBasemap has no option '{py_str(args[i])}' (it takes Attribution, DisplayName and MaxZoomLevel).", 'addCustomBasemap')
    CUSTOM_BASEMAPS[name] = spec
    return None


@bi('removeCustomBasemap', arr=False)
def removeCustomBasemap(nargout, *args):
    name = sval(args[0], 'basemap name', 'removeCustomBasemap')
    if name not in CUSTOM_BASEMAPS:
        raise err('map:basemap:notCustom', f"'{name}' is not a basemap added with addCustomBasemap.", 'removeCustomBasemap')
    del CUSTOM_BASEMAPS[name]
    return None


# ---- raster references -------------------------------------------------------------------------------------------------------------

class RasterRef(Obj):
    """georasterref, georefcells, georefpostings and maprefcells: where a
    raster's rows and columns lie, in latitude and longitude or in x and y."""
    __slots__ = ('geo', 'lim1', 'lim2', 'size', 'cells', 'col_dir', 'row_dir', 'crs')
    is_handle = False

    def __init__(self, geo, lim1, lim2, size, cells=True, col_dir='north', row_dir='east', crs=None):
        self.geo = geo                      # True: lat/lon, False: x/y
        self.lim1, self.lim2 = list(lim1), list(lim2)    # latlim and lonlim, or xlim and ylim
        self.size = tuple(int(s) for s in size)
        self.cells = cells
        self.col_dir = col_dir              # the way the columns run: 'north' (rows from the south) or 'south'
        self.row_dir = row_dir
        self.crs = crs

    @property
    def cls(self):
        if self.geo:
            return 'map.rasterref.GeographicCellsReference' if self.cells else 'map.rasterref.GeographicPostingsReference'
        return 'map.rasterref.MapCellsReference' if self.cells else 'map.rasterref.MapPostingsReference'

    def value_copy(self):
        return RasterRef(self.geo, self.lim1, self.lim2, self.size, self.cells, self.col_dir, self.row_dir, self.crs)

    def _lines(self, n, lim, flip):
        if self.cells:
            step = (lim[1] - lim[0]) / n
            c = lim[0] + step * (np.arange(n) + 0.5)
        else:
            c = np.linspace(lim[0], lim[1], n)
        return c[::-1] if flip else c

    def grid_latlon(self, shape):
        m, n = shape[:2]
        lat = self._lines(m, self.lim1, self.col_dir == 'south')
        lon = self._lines(n, self.lim2, self.row_dir == 'west')
        LO, LA = np.meshgrid(lon, lat)
        return LA, LO

    def grid_xy(self, shape):
        m, n = shape[:2]
        x = self._lines(n, self.lim1, self.row_dir == 'west')
        y = self._lines(m, self.lim2, self.col_dir == 'south')
        return np.meshgrid(x, y)

    def props(self):
        m, n = self.size
        d = {}
        if self.geo:
            d['LatitudeLimits'] = np.array([self.lim1])
            d['LongitudeLimits'] = np.array([self.lim2])
            d['RasterSize'] = np.array([[float(m), float(n)]])
            d['RasterInterpretation'] = Char.of('cells' if self.cells else 'postings')
            d['ColumnsStartFrom'] = Char.of(self.col_dir if self.col_dir != 'north' else 'south') if False else Char.of('north' if self.col_dir == 'south' else 'south')
            d['RowsStartFrom'] = Char.of('west' if self.row_dir == 'east' else 'east')
            k = m if self.cells else max(m - 1, 1)
            l = n if self.cells else max(n - 1, 1)
            d['CellExtentInLatitude' if self.cells else 'SampleSpacingInLatitude'] = (self.lim1[1] - self.lim1[0]) / k
            d['CellExtentInLongitude' if self.cells else 'SampleSpacingInLongitude'] = (self.lim2[1] - self.lim2[0]) / l
            d['AngleUnit'] = Char.of('degree')
        else:
            d['XWorldLimits'] = np.array([self.lim1])
            d['YWorldLimits'] = np.array([self.lim2])
            d['RasterSize'] = np.array([[float(m), float(n)]])
            d['RasterInterpretation'] = Char.of('cells' if self.cells else 'postings')
            d['ColumnsStartFrom'] = Char.of('north' if self.col_dir == 'south' else 'south')
            d['RowsStartFrom'] = Char.of('west' if self.row_dir == 'east' else 'east')
            k = n if self.cells else max(n - 1, 1)
            l = m if self.cells else max(m - 1, 1)
            d['CellExtentInWorldX' if self.cells else 'SampleSpacingInWorldX'] = (self.lim1[1] - self.lim1[0]) / k
            d['CellExtentInWorldY' if self.cells else 'SampleSpacingInWorldY'] = (self.lim2[1] - self.lim2[0]) / l
        if self.crs is not None:
            d['ProjectedCRS' if not self.geo else 'GeographicCRS'] = self.crs
        return d

    def getprop(self, name):
        for k, v in self.props().items():
            if k.lower() == name.lower():
                return v
        return super().getprop(name)

    def setprop(self, name, value):
        key = name.lower()
        if key in ('latitudelimits', 'xworldlimits'):
            self.lim1 = [float(x) for x in darr(value).reshape(-1)[:2]]
        elif key in ('longitudelimits', 'yworldlimits'):
            self.lim2 = [float(x) for x in darr(value).reshape(-1)[:2]]
        elif key == 'rastersize':
            self.size = tuple(int(x) for x in darr(value).reshape(-1)[:2])
        elif key == 'columnsstartfrom':
            self.col_dir = 'south' if py_str(value).lower() == 'north' else 'north'
        elif key == 'rowsstartfrom':
            self.row_dir = 'east' if py_str(value).lower() == 'west' else 'west'
        else:
            raise err('map:rasterref:readOnly', f"{name} cannot be set here.")

    def propnames(self):
        return list(self.props())

    def display_lines(self):
        p = self.props()
        w = max(len(k) for k in p)
        lines = [f'  {self.cls.split(".")[-1]} with properties:', '']
        for k, v in p.items():
            if isinstance(v, Char):
                sv = f"'{v.str()}'"
            elif isinstance(v, np.ndarray):
                sv = '[' + ' '.join(f'{x:g}' for x in v.reshape(-1)) + ']'
            elif isinstance(v, float):
                sv = f'{v:g}'
            else:
                sv = f'[1×1 {getattr(v, "cls", "object")}]'
            lines.append(f'    {k.rjust(w)}: {sv}')
        return lines

    def intrinsic_of(self, a, b):
        """Fractional row and column (1-based) of latitude and longitude (or x and y)."""
        m, n = self.size
        if self.geo:
            lat, lon = a, b
            fr = (lat - self.lim1[0]) / (self.lim1[1] - self.lim1[0])
            fc = (lon - self.lim2[0]) / (self.lim2[1] - self.lim2[0])
        else:
            x, y = a, b
            fc = (x - self.lim1[0]) / (self.lim1[1] - self.lim1[0])
            fr = (y - self.lim2[0]) / (self.lim2[1] - self.lim2[0])
        if self.col_dir == 'south':
            fr = 1 - fr
        if self.row_dir == 'west':
            fc = 1 - fc
        if self.cells:
            return 0.5 + fr * m, 0.5 + fc * n
        return 1 + fr * (m - 1), 1 + fc * (n - 1)


def _ref_args(args, geo, fn):
    args = list(args)
    size = darr(args[0]).reshape(-1)[:2]
    lim1 = [float(x) for x in darr(args[1]).reshape(-1)[:2]]
    lim2 = [float(x) for x in darr(args[2]).reshape(-1)[:2]]
    return RasterRef(geo, lim1, lim2, size, cells=fn.endswith('cells'), col_dir='south' if geo else 'south')


def _three_inputs(args, fn):
    """The limits and raster size of a reference object: none, or all three."""
    if len(args) < 3:
        raise err('MATLAB:minrhs', 'Give the two limits and the raster size (or nothing, for the default).', fn)
    for k in (0, 1):
        if is_str(args[k]) or numel(args[k]) != 2:
            raise err(f'map:{fn}:limits', 'The limits have two elements each.', fn)
    if is_str(args[2]) or numel(args[2]) < 2:
        raise err(f'map:{fn}:rasterSize', 'The raster size is [rows columns].', fn)


@bi('georefcells', arr=False)
def georefcells(nargout, *args):
    if not args:
        return RasterRef(True, [0.5, 2.5], [0.5, 2.5], (2, 2))
    _three_inputs(args, 'georefcells')
    latlim, lonlim, rsize = args[0], args[1], args[2]
    rs = darr(rsize).reshape(-1)
    return RasterRef(True, darr(latlim).reshape(-1), darr(lonlim).reshape(-1), rs[:2], cells=True, col_dir='north' if not args[3:] else 'north')


@bi('georefpostings', arr=False)
def georefpostings(nargout, *args):
    if not args:
        return RasterRef(True, [1.0, 2.0], [1.0, 2.0], (2, 2), cells=False)
    _three_inputs(args, 'georefpostings')
    latlim, lonlim, rsize = args[0], args[1], args[2]
    return RasterRef(True, darr(latlim).reshape(-1), darr(lonlim).reshape(-1), darr(rsize).reshape(-1)[:2], cells=False)


@bi('maprefcells', arr=False)
def maprefcells(nargout, *args):
    if not args:
        return RasterRef(False, [0.5, 2.5], [0.5, 2.5], (2, 2), cells=True)
    _three_inputs(args, 'maprefcells')
    xlim, ylim, rsize = args[0], args[1], args[2]
    return RasterRef(False, darr(xlim).reshape(-1), darr(ylim).reshape(-1), darr(rsize).reshape(-1)[:2], cells=True)


@bi('maprefpostings', arr=False)
def maprefpostings(nargout, *args):
    if not args:
        return RasterRef(False, [1.0, 2.0], [1.0, 2.0], (2, 2), cells=False)
    _three_inputs(args, 'maprefpostings')
    xlim, ylim, rsize = args[0], args[1], args[2]
    return RasterRef(False, darr(xlim).reshape(-1), darr(ylim).reshape(-1), darr(rsize).reshape(-1)[:2], cells=False)


@bi('georasterref', arr=False)
def georasterref(nargout, *args):
    names = {}
    for i in range(0, len(args) - 1, 2):
        names[sval(args[i], 'property', 'georasterref').lower()] = args[i + 1]
    size = darr(names.get('rastersize', np.array([[1.0, 1.0]]))).reshape(-1)[:2]
    latlim = darr(names.get('latitudelimits', np.array([[0.0, 1.0]]))).reshape(-1)
    lonlim = darr(names.get('longitudelimits', np.array([[0.0, 1.0]]))).reshape(-1)
    interp = py_str(names['rasterinterpretation']).lower() if 'rasterinterpretation' in names else 'cells'
    r = RasterRef(True, latlim, lonlim, size, cells=interp == 'cells')
    if 'columnsstartfrom' in names:
        r.setprop('ColumnsStartFrom', names['columnsstartfrom'])
    return r


@bi('geographicToIntrinsic', nout=2)
def geographicToIntrinsic(nargout, *args):
    if len(args) != 3 or not isinstance(args[0], RasterRef):
        raise err('map:geographicToIntrinsic:inputs', 'geographicToIntrinsic takes a raster reference and two coordinate arrays.', 'geographicToIntrinsic')
    R_ = args[0]
    xi_r, xi_c = R_.intrinsic_of(darr(args[1]), darr(args[2]))
    return (out(xi_c), out(xi_r)) if nargout > 1 else out(xi_c)


@bi('worldToIntrinsic', nout=2)
def worldToIntrinsic(nargout, *args):
    if len(args) != 3 or not isinstance(args[0], RasterRef):
        raise err('map:worldToIntrinsic:inputs', 'worldToIntrinsic takes a raster reference and two coordinate arrays.', 'worldToIntrinsic')
    R_ = args[0]
    xi_r, xi_c = R_.intrinsic_of(darr(args[1]), darr(args[2]))
    return (out(xi_c), out(xi_r)) if nargout > 1 else out(xi_c)


@bi('geointerp')
def geointerp(nargout, *args):
    A, R_ = darr(args[0]), args[1]
    lat, lon = darr(args[2]), darr(args[3])
    method = py_str(args[4]).lower() if len(args) > 4 else 'linear'
    r, c = R_.intrinsic_of(lat, lon)
    from scipy.ndimage import map_coordinates
    order = {'nearest': 0, 'linear': 1, 'cubic': 3}.get(method, 1)
    v = map_coordinates(A, [np.asarray(r).reshape(-1) - 1, np.asarray(c).reshape(-1) - 1], order=order, mode='nearest' if order == 0 else 'constant', cval=np.nan)
    m, n = A.shape[:2]
    rr, cc = np.asarray(r).reshape(-1), np.asarray(c).reshape(-1)
    v = np.where((rr < 0.5) | (rr > m + 0.5) | (cc < 0.5) | (cc > n + 0.5), np.nan, v)
    return out(v.reshape(np.shape(lat)))


# ---- shapefiles -------------------------------------------------------------------------------------------------------------------

_SHP_TYPES = {0: 'Null Shape', 1: 'Point', 3: 'PolyLine', 5: 'Polygon', 8: 'MultiPoint', 11: 'PointZ', 13: 'PolyLineZ', 15: 'PolygonZ',
              18: 'MultiPointZ', 21: 'PointM', 23: 'PolyLineM', 25: 'PolygonM', 28: 'MultiPointM', 31: 'MultiPatch'}
_GEOMETRY = {1: 'Point', 11: 'Point', 21: 'Point', 8: 'MultiPoint', 18: 'MultiPoint', 28: 'MultiPoint', 3: 'Line', 13: 'Line', 23: 'Line',
             5: 'Polygon', 15: 'Polygon', 25: 'Polygon'}


def _resolve(fname, fn):
    from .iofun import abspath
    return abspath(fname)


def _shp_paths(fname, fn):
    base = _resolve(fname, fn)
    root, ext = os.path.splitext(base)
    if ext.lower() not in ('.shp', '.dbf', '.shx', ''):
        root = base
    shp = root + '.shp'
    if not os.path.isfile(shp):
        alt = [root + e for e in ('.SHP',)]
        shp = next((p for p in alt if os.path.isfile(p)), shp)
    if not os.path.isfile(shp):
        raise err('map:shapefile:fileNotFound', f"Unable to find the shapefile '{fname}'.", fn)
    dbf = next((root + e for e in ('.dbf', '.DBF') if os.path.isfile(root + e)), None)
    return shp, dbf


async def _shp_source(fname, fn):
    """A shapefile's (shape type, bounding box, records, attribute names, types,
    rows, file name); for landareas, worldlakes, worldrivers and worldcities,
    when no such file is found, Natural Earth's (geodata.py)."""
    try:
        shp, dbf = _shp_paths(fname, fn)
    except MError as e:
        key = GD.dataset(fname, 'shp')
        if e.identifier != 'map:shapefile:fileNotFound' or key is None:
            raise
        return (*await GD.shapes(key), key + '.shp')
    stype, bbox, recs = _read_shp(shp, fn)
    names, types, rows = _read_dbf(dbf, fn)
    return stype, bbox, recs, names, types, rows, shp


def _read_shp(path, fn):
    with open(path, 'rb') as fh:
        data = fh.read()
    if len(data) < 100 or struct.unpack('>i', data[:4])[0] != 9994:
        raise err('map:shapefile:invalidFile', f"'{os.path.basename(path)}' is not a shapefile (it has no shapefile header).", fn)
    file_len = struct.unpack('>i', data[24:28])[0] * 2
    stype = struct.unpack('<i', data[32:36])[0]
    bbox = struct.unpack('<4d', data[36:68])
    recs = []
    pos = 100
    end = min(len(data), file_len)
    while pos + 8 <= end:
        num_, clen = struct.unpack('>2i', data[pos:pos + 8])
        clen *= 2
        body = data[pos + 8:pos + 8 + clen]
        pos += 8 + clen
        if len(body) < 4:
            break
        t = struct.unpack('<i', body[:4])[0]
        if t == 0:
            recs.append((0, None, np.zeros(0), np.zeros(0)))
            continue
        if t in (1, 11, 21):
            x, y = struct.unpack('<2d', body[4:20])
            recs.append((t, (x, y, x, y), np.array([x]), np.array([y])))
            continue
        bb = struct.unpack('<4d', body[4:36])
        if t in (8, 18, 28):
            n = struct.unpack('<i', body[36:40])[0]
            if 40 + 16 * n > len(body):
                raise err('map:shapefile:corrupt', f'A record of {os.path.basename(path)} is shorter than its points.', fn)
            pts = np.frombuffer(body, '<f8', 2 * n, 40).reshape(n, 2)
            recs.append((t, bb, pts[:, 0].copy(), pts[:, 1].copy()))
            continue
        if t in (3, 13, 23, 5, 15, 25):
            nparts, npts = struct.unpack('<2i', body[36:44])
            if nparts < 0 or npts < 0 or 44 + 4 * nparts + 16 * npts > len(body):
                raise err('map:shapefile:corrupt', f'A record of {os.path.basename(path)} is shorter than its parts and points.', fn)
            parts = list(struct.unpack(f'<{nparts}i', body[44:44 + 4 * nparts]))
            pts = np.frombuffer(body, '<f8', 2 * npts, 44 + 4 * nparts).reshape(npts, 2)
            xs, ys = [], []
            for k, p0 in enumerate(parts):
                p1 = parts[k + 1] if k + 1 < nparts else npts
                xs += list(pts[p0:p1, 0]) + [np.nan]
                ys += list(pts[p0:p1, 1]) + [np.nan]
            recs.append((t, bb, np.array(xs), np.array(ys)))
            continue
        recs.append((t, None, np.zeros(0), np.zeros(0)))
    return stype, bbox, recs


def _read_dbf(path, fn):
    """dBASE III table: (field names, types, rows of values)."""
    if path is None:
        return [], [], []
    with open(path, 'rb') as fh:
        data = fh.read()
    if len(data) < 32:
        return [], [], []
    nrec, hlen, rlen = struct.unpack('<IHH', data[4:12])
    fields = []
    pos = 32
    while pos + 32 <= hlen and data[pos] != 0x0D:
        name = data[pos:pos + 11].split(b'\x00')[0].decode('latin-1').strip()
        ftype = chr(data[pos + 11])
        flen, fdec = data[pos + 16], data[pos + 17]
        fields.append((name, ftype, flen, fdec))
        pos += 32
    rows = []
    for r in range(nrec):
        off = hlen + r * rlen
        rec = data[off:off + rlen]
        if len(rec) < rlen:
            break
        if rec[:1] == b'*':
            continue
        p = 1
        row = []
        for name, ftype, flen, fdec in fields:
            raw = rec[p:p + flen]
            p += flen
            txt = raw.decode('utf-8', 'replace').strip() if True else ''
            if ftype in 'NF':
                try:
                    row.append(float(txt) if txt else math.nan)
                except ValueError:
                    row.append(math.nan)
            elif ftype == 'L':
                row.append(txt.upper() in ('Y', 'T'))
            else:
                row.append(txt)
        rows.append(row)
    return [f[0] for f in fields], [f[1] for f in fields], rows


def _field_name(n):
    import re
    s = re.sub(r'\W', '_', n)
    if not s or not s[0].isalpha():
        s = 'x' + s
    return s[:63]


@bi('shaperead', nout=2, aw=True, arr=False)
async def shaperead(nargout, *args):
    if not args:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'shaperead')
    fname = sval(args[0], 'file name', 'shaperead')
    opts = {}
    for i in range(1, len(args) - 1, 2):
        opts[sval(args[i], 'option', 'shaperead').lower()] = args[i + 1]
    geo = bool(num(opts['usegeocoords'])) if 'usegeocoords' in opts and not is_str(opts['usegeocoords']) else \
        (py_str(opts['usegeocoords']).lower() in ('true', 'on') if 'usegeocoords' in opts else False)
    stype, bbox, recs, names, types, rows, _ = await _shp_source(fname, 'shaperead')
    keep = list(range(len(recs)))
    if 'recordnumbers' in opts:
        want = [int(v) - 1 for v in darr(opts['recordnumbers']).reshape(-1)]
        keep = [k for k in keep if k in want]
    if 'boundingbox' in opts:
        b = darr(opts['boundingbox'])
        keep = [k for k in keep if recs[k][1] is not None and not (recs[k][1][2] < b[0, 0] or recs[k][1][0] > b[1, 0] or recs[k][1][3] < b[0, 1] or recs[k][1][1] > b[1, 1])]
    attrs = names
    if 'attributes' in opts:
        a = opts['attributes']
        want = [py_str(x) for x in a.a.reshape(-1)] if type(a) is Cell else [py_str(a)]
        attrs = [n for n in names if n in want]
    if 'selector' in opts:
        sel = opts['selector']
        fh, fields = sel.a.reshape(-1)[0], [py_str(x) for x in sel.a.reshape(-1)[1:]]
        idx = [names.index(f) for f in fields]
        new = []
        for k in keep:
            vals = [(rows[k][i] if k < len(rows) else math.nan) for i in idx]
            vals = [Char.of(v) if isinstance(v, str) else float(v) for v in vals]
            if bool(np.all(darr(fh.scall(1, *vals)))):
                new.append(k)
        keep = new
    fields = ['Geometry', 'BoundingBox', 'Lon' if geo else 'X', 'Lat' if geo else 'Y'] + [_field_name(n) for n in attrs]
    S = Struct((len(keep), 1), {f: np.empty((len(keep), 1), object) for f in fields})
    for j, k in enumerate(keep):
        t, bb, xs, ys = recs[k]
        S.f['Geometry'][j, 0] = Char.of(_GEOMETRY.get(t, 'Null'))
        S.f['BoundingBox'][j, 0] = np.array([[bb[0], bb[1]], [bb[2], bb[3]]]) if bb else EMPTY()
        S.f[fields[2]][j, 0] = out(xs.reshape(1, -1)) if xs.size else np.zeros((1, 0))
        S.f[fields[3]][j, 0] = out(ys.reshape(1, -1)) if ys.size else np.zeros((1, 0))
        for nm in attrs:
            v = rows[k][names.index(nm)] if k < len(rows) else math.nan
            S.f[_field_name(nm)][j, 0] = Char.of(v) if isinstance(v, str) else (bool(v) if isinstance(v, bool) else float(v))
    if nargout > 1:
        A = Struct((len(keep), 1), {_field_name(n): np.empty((len(keep), 1), object) for n in attrs})
        for j, k in enumerate(keep):
            for nm in attrs:
                v = rows[k][names.index(nm)] if k < len(rows) else math.nan
                A.f[_field_name(nm)][j, 0] = Char.of(v) if isinstance(v, str) else float(v)
        geom = Struct((len(keep), 1), {f: S.f[f] for f in fields[:4]})
        return geom, A
    return S


@bi('shapeinfo', aw=True, arr=False)
async def shapeinfo(nargout, *args):
    fname = sval(args[0], 'file name', 'shapeinfo')
    stype, bbox, recs, names, types, rows, shp = await _shp_source(fname, 'shapeinfo')
    tmap = {'N': 'double', 'F': 'double', 'C': 'char', 'L': 'logical', 'D': 'char'}
    attrs = Struct((len(names), 1), {'Name': np.empty((len(names), 1), object), 'Type': np.empty((len(names), 1), object)})
    for i, (n, t) in enumerate(zip(names, types)):
        attrs.f['Name'][i, 0] = Char.of(n)
        attrs.f['Type'][i, 0] = Char.of({'N': 'Numeric', 'F': 'Numeric', 'C': 'Character', 'L': 'Logical', 'D': 'Date'}.get(t, 'Character'))
    return Struct.scalar({'Filename': Char.of(shp), 'ShapeType': Char.of(_SHP_TYPES.get(stype, 'Unknown')),
                          'BoundingBox': np.array([[bbox[0], bbox[1]], [bbox[2], bbox[3]]]), 'NumFeatures': float(len(recs)),
                          'Attributes': attrs})


@bi('shapewrite', arr=False)
def shapewrite(nargout, *args):
    S = args[0]
    fname = sval(args[1], 'file name', 'shapewrite')
    if type(S) is not Struct or 'Geometry' not in S.f:
        raise err('map:shapewrite:invalidInput', 'shapewrite takes a struct array with a Geometry field and X and Y (or Lat and Lon).', 'shapewrite')
    base = _resolve(fname, 'shapewrite')
    root = os.path.splitext(base)[0]
    n = S.size
    xs_f, ys_f = ('X', 'Y') if 'X' in S.f else ('Lon', 'Lat')
    geoms = {py_str(_sget(S, 'Geometry', i)).lower() for i in range(n)}
    if len(geoms) > 1:
        raise err('map:shapewrite:mixedGeometry', 'All the features of a shapefile have one Geometry.', 'shapewrite')
    g = geoms.pop() if geoms else 'point'
    stype = {'point': 1, 'multipoint': 8, 'line': 3, 'polyline': 3, 'polygon': 5}.get(g)
    if stype is None:
        raise err('map:shapewrite:geometry', f"'{g}' is not a Geometry shapewrite knows: Point, MultiPoint, Line or Polygon.", 'shapewrite')
    bodies = []
    allx, ally = [], []
    for i in range(n):
        x = darr(_sget(S, xs_f, i)).reshape(-1)
        y = darr(_sget(S, ys_f, i)).reshape(-1)
        parts = _nan_parts(x, y)
        px = np.concatenate([p for p, _ in parts]) if parts else np.zeros(0)
        py = np.concatenate([q for _, q in parts]) if parts else np.zeros(0)
        allx += list(px)
        ally += list(py)
        if stype == 1:
            body = struct.pack('<i2d', 1, float(px[0]) if px.size else 0.0, float(py[0]) if py.size else 0.0)
        else:
            bb = struct.pack('<4d', px.min() if px.size else 0, py.min() if py.size else 0, px.max() if px.size else 0, py.max() if py.size else 0)
            if stype == 8:
                body = struct.pack('<i', 8) + bb + struct.pack('<i', px.size) + np.column_stack([px, py]).astype('<f8').tobytes()
            else:
                starts, k = [], 0
                for p, _ in parts:
                    starts.append(k)
                    k += p.size
                body = struct.pack('<i', stype) + bb + struct.pack('<2i', len(parts), px.size) + struct.pack(f'<{len(parts)}i', *starts) + \
                    np.column_stack([px, py]).astype('<f8').tobytes()
        bodies.append(body)
    bbox = (min(allx) if allx else 0.0, min(ally) if ally else 0.0, max(allx) if allx else 0.0, max(ally) if ally else 0.0)

    def header(total_bytes):
        return struct.pack('>7i', 9994, 0, 0, 0, 0, 0, total_bytes // 2) + struct.pack('<2i', 1000, stype) + struct.pack('<4d', *bbox) + struct.pack('<4d', 0, 0, 0, 0)
    shp = bytearray()
    shx = bytearray()
    offset = 100
    for i, body in enumerate(bodies):
        rec = struct.pack('>2i', i + 1, len(body) // 2) + body
        shx += struct.pack('>2i', offset // 2, len(body) // 2)
        shp += rec
        offset += len(rec)
    with open(root + '.shp', 'wb') as fh:
        fh.write(header(100 + len(shp)) + bytes(shp))
    with open(root + '.shx', 'wb') as fh:
        fh.write(header(100 + len(shx)) + bytes(shx))
    # the attributes: every other field of numbers or text
    skip = {'Geometry', 'BoundingBox', 'X', 'Y', 'Lat', 'Lon'}
    fields = []
    for k in S.f:
        if k in skip:
            continue
        vals = [_sget(S, k, i) for i in range(n)]
        if all(isinstance(v, (float, bool)) or (type(v) is np.ndarray and v.size == 1) for v in vals):
            nums = [float(np.asarray(v, float).reshape(-1)[0]) for v in vals]
            fields.append((k[:10], 'N', 19, 11 if any(x != int(x) for x in nums if math.isfinite(x)) else 0, nums))
        elif all(is_str(v) for v in vals):
            txt = [py_str(v) for v in vals]
            fields.append((k[:10], 'C', max(1, min(254, max((len(t.encode('utf-8')) for t in txt), default=1))), 0, txt))
    rlen = 1 + sum(f[2] for f in fields)
    hlen = 32 + 32 * len(fields) + 1
    today = datetime.date.today()
    dbf = bytearray(struct.pack('<4BIHH20x', 3, today.year - 1900, today.month, today.day, n, hlen, rlen))
    for name, t, ln, dec, _ in fields:
        dbf += name.encode('latin-1', 'replace')[:11].ljust(11, b'\x00') + t.encode() + b'\x00' * 4 + bytes([ln, dec]) + b'\x00' * 14
    dbf += b'\x0D'
    for i in range(n):
        dbf += b' '
        for name, t, ln, dec, vals in fields:
            v = vals[i]
            if t == 'N':
                s = '' if not math.isfinite(v) else (f'{v:.{dec}f}' if dec else f'{int(round(v))}')
                dbf += s.rjust(ln)[:ln].encode()
            else:
                dbf += v.encode('utf-8')[:ln].ljust(ln, b' ')
    dbf += b'\x1A'
    with open(root + '.dbf', 'wb') as fh:
        fh.write(bytes(dbf))
    from .iofun import files_changed
    files_changed()
    return None


# ---- GeoTIFF ----------------------------------------------------------------------------------------------------------------------------

async def _pillow():
    try:
        from PIL import Image
        return Image
    except ImportError:
        import sys
        if sys.platform != 'emscripten':
            raise err('map:geotiff:noPillow', 'Reading GeoTIFF files needs the Pillow package (pip install pillow).', 'readgeoraster')
        import pyodide_js
        await pyodide_js.loadPackage('pillow')
        from PIL import Image
        return Image


def _geokeys(tags):
    keys = {}
    gk = tags.get(34735)
    if gk:
        gk = list(gk)
        n = gk[3] if len(gk) > 3 else 0
        for i in range(n):
            k, loc, cnt, val = gk[4 + 4 * i:8 + 4 * i]
            if loc == 0:
                keys[k] = val
    return keys


async def _read_geotiff(fname, fn):
    Image = await _pillow()
    path = _resolve(fname, fn)
    if not os.path.isfile(path):
        raise err('map:geotiff:fileNotFound', f"Unable to find the file '{fname}'.", fn)
    im = Image.open(path)
    tags = dict(im.tag_v2) if hasattr(im, 'tag_v2') else {}
    A = np.asarray(im)
    scale = tags.get(33550)
    tie = tags.get(33922)
    keys = _geokeys(tags)
    if scale is None or tie is None:
        raise err('map:geotiff:noReference', f"'{fname}' has no GeoTIFF georeference (ModelPixelScale and ModelTiepoint).", fn)
    sx, sy = float(scale[0]), float(scale[1])
    i0, j0, _, x0, y0, _ = (float(v) for v in tie[:6])
    m, n = A.shape[:2]
    point = keys.get(1025) == 2
    geo = keys.get(1024) == 2
    # the corner of pixel (i0, j0) is at (x0, y0); rows run down from the top
    left = x0 - i0 * sx
    top = y0 + j0 * sy
    if point:
        lim_x = [left, left + (n - 1) * sx]
        lim_y = [top - (m - 1) * sy, top]
    else:
        lim_x = [left, left + n * sx]
        lim_y = [top - m * sy, top]
    if geo:
        Rr = RasterRef(True, lim_y, lim_x, (m, n), cells=not point, col_dir='south')
    else:
        code = keys.get(3072)
        crs = None
        if code and M.epsg(int(code)) is not None:
            nm, kind, ell, params, gcrs = M.epsg(int(code))
            a, e, *_ = M.ellipsoid_ae(ell if ell != 'sphere6378137' else 'wgs84')
            crs = CRS(int(code), nm, kind, ell, params, gcrs, proj=M.make(kind, a, e if ell != 'sphere6378137' else 0.0, **params))
        Rr = RasterRef(False, lim_x, lim_y, (m, n), cells=not point, col_dir='south', crs=crs)
    return A, Rr, tags, keys


@bi('readgeoraster', nout=3, aw=True, arr=False)
async def readgeoraster(nargout, *args):
    fname = sval(args[0], 'file name', 'readgeoraster')
    A, Rr, tags, keys = await _read_geotiff(fname, 'readgeoraster')
    out_A = A if A.dtype != np.float64 else A
    if A.dtype.kind == 'f' and A.dtype != np.float64 and A.dtype != np.float32:
        out_A = A.astype(np.float64)
    if A.dtype == np.int64:
        out_A = A.astype(np.float64)
    if nargout > 2:
        cmap = EMPTY()
        return out_A, Rr, cmap
    return (out_A, Rr) if nargout > 1 else out_A


@bi('geotiffinfo', aw=True, arr=False)
async def geotiffinfo(nargout, *args):
    fname = sval(args[0], 'file name', 'geotiffinfo')
    A, Rr, tags, keys = await _read_geotiff(fname, 'geotiffinfo')
    return Struct.scalar({'Filename': Char.of(_resolve(fname, 'geotiffinfo')), 'Height': float(A.shape[0]), 'Width': float(A.shape[1]),
                          'BitDepth': float(A.dtype.itemsize * 8 * (A.shape[2] if A.ndim == 3 else 1)),
                          'ModelType': Char.of({1: 'ModelTypeProjected', 2: 'ModelTypeGeographic', 3: 'ModelTypeGeocentric'}.get(keys.get(1024), '')),
                          'PCS': Char.of(Rr.crs.name if (not Rr.geo and Rr.crs) else ''),
                          'SpatialRef': Rr})


@bi('geotiffread', nout=3, aw=True, arr=False)
async def geotiffread(nargout, *args):
    return await readgeoraster(nargout, *args)
