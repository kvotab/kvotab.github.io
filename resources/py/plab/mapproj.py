"""Map projections and geodesy, in NumPy: the formulas of the textbooks
(Snyder's Map Projections, a Working Manual; Krüger's series for the
transverse Mercator; Vincenty's geodesics on the ellipsoid), for the
mapping functions in builtins/mapping.py.

Angles are in degrees in and out; lengths in the ellipsoid's units. An
ellipsoid is (a, e): semimajor axis and eccentricity (e = 0 a sphere).
"""
import math

import numpy as np

D2R = math.pi / 180.0
R2D = 180.0 / math.pi


# ---- the ellipsoid's latitudes ------------------------------------------------------------------------------

def _q(phi, e):
    """Snyder's q (for the authalic latitude and the equal-area projections)."""
    s = np.sin(phi)
    if e == 0:
        return 2 * s
    es = e * s
    return (1 - e * e) * (s / (1 - es * es) - np.log((1 - es) / (1 + es)) / (2 * e))


def _tsfn(phi, e):
    """Snyder's t (conformal: Mercator, Lambert conformal conic, polar stereographic)."""
    s = np.sin(phi)
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.tan(math.pi / 4 - phi / 2) / ((1 - e * s) / (1 + e * s)) ** (e / 2)


def _phi_from_t(t, e):
    phi = math.pi / 2 - 2 * np.arctan(t)
    for _ in range(30):
        s = np.sin(phi)
        new = math.pi / 2 - 2 * np.arctan(t * ((1 - e * s) / (1 + e * s)) ** (e / 2))
        if np.all(np.abs(new - phi) < 1e-13):
            phi = new
            break
        phi = new
    return phi


def _msfn(phi, e):
    return np.cos(phi) / np.sqrt(1 - (e * np.sin(phi)) ** 2)


def meridian_arc(phi, a, e):
    """The distance along the meridian from the equator to latitude phi (radians)."""
    e2 = e * e
    if e2 == 0:
        return a * phi
    e4, e6 = e2 * e2, e2 * e2 * e2
    return a * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * np.sin(2 * phi)
                + (15 * e4 / 256 + 45 * e6 / 1024) * np.sin(4 * phi) - (35 * e6 / 3072) * np.sin(6 * phi))


def authalic_radius(a, e):
    if e == 0:
        return a
    return a * math.sqrt(_q(math.pi / 2, e) / 2)


# ---- projections ---------------------------------------------------------------------------------------------

class Proj:
    """A projection: fwd(lat, lon) -> (x, y), inv(x, y) -> (lat, lon), in
    degrees and the ellipsoid's units, with false easting and northing."""
    name = ''
    conic = False

    def __init__(self, a=1.0, e=0.0, lat0=0.0, lon0=0.0, parallels=None, k0=1.0, fe=0.0, fn=0.0, **kw):
        self.a, self.e = float(a), float(e)
        self.lat0, self.lon0 = float(lat0), float(lon0)
        self.parallels = list(parallels) if parallels is not None else None
        self.k0 = float(k0)
        self.fe, self.fn = float(fe), float(fn)
        self.kw = kw
        self.setup()

    def setup(self):
        pass

    def dlon(self, lon):
        return (np.asarray(lon, float) - self.lon0 + 180.0) % 360.0 - 180.0

    def fwd(self, lat, lon):
        lat = np.asarray(lat, float)
        lon = np.asarray(lon, float)
        with np.errstate(all='ignore'):
            x, y = self._fwd(lat * D2R, self.dlon(lon) * D2R)
        return x + self.fe, y + self.fn

    def inv(self, x, y):
        x = np.asarray(x, float) - self.fe
        y = np.asarray(y, float) - self.fn
        with np.errstate(all='ignore'):
            phi, lam = self._inv(x, y)
        lon = (lam * R2D + self.lon0 + 180.0) % 360.0 - 180.0
        return phi * R2D, lon

    def visible(self, lat, lon):
        """Points that the projection shows (the hemisphere an azimuthal view faces)."""
        return np.ones(np.shape(lat), bool)


class EqdCylin(Proj):
    name = 'eqdcylin'

    def setup(self):
        sp = self.parallels[0] if self.parallels else 0.0
        self.c = math.cos(sp * D2R)

    def _fwd(self, phi, lam):
        return self.a * lam * self.c, self.a * (phi - self.lat0 * D2R)

    def _inv(self, x, y):
        return y / self.a + self.lat0 * D2R, x / (self.a * self.c)


class Miller(Proj):
    name = 'miller'

    def _fwd(self, phi, lam):
        return self.a * lam, self.a * 1.25 * np.log(np.tan(math.pi / 4 + 0.4 * phi))

    def _inv(self, x, y):
        return 2.5 * np.arctan(np.exp(0.8 * y / self.a)) - 0.625 * math.pi, x / self.a


class EqaCylin(Proj):
    """Lambert's cylindrical equal-area (Behrmann and kin with a standard parallel)."""
    name = 'eqacylin'

    def setup(self):
        sp = self.parallels[0] if self.parallels else 0.0
        self.k = _msfn(sp * D2R, self.e)
        self.qp = _q(math.pi / 2, self.e)

    def _fwd(self, phi, lam):
        return self.a * self.k * lam, self.a * _q(phi, self.e) / (2 * self.k)

    def _inv(self, x, y):
        q = 2 * y * self.k / self.a
        beta = np.arcsin(np.clip(q / self.qp, -1, 1))
        return _lat_from_authalic(beta, self.e), x / (self.a * self.k)


def _lat_from_authalic(beta, e):
    """The latitude of an authalic latitude: the series, then Snyder's
    iteration on q to round-off."""
    if e == 0:
        return beta
    e2 = e * e
    e4, e6 = e2 * e2, e2 * e2 * e2
    phi = (beta + (e2 / 3 + 31 * e4 / 180 + 517 * e6 / 5040) * np.sin(2 * beta) + (23 * e4 / 360 + 251 * e6 / 3780) * np.sin(4 * beta)
           + (761 * e6 / 45360) * np.sin(6 * beta))
    q = _q(math.pi / 2, e) * np.sin(beta)
    for _ in range(3):
        s = np.sin(phi)
        es2 = 1 - e2 * s * s
        with np.errstate(invalid='ignore', divide='ignore'):
            d = es2 * es2 / (2 * np.cos(phi)) * (q / (1 - e2) - s / es2 + np.log((1 - e * s) / (1 + e * s)) / (2 * e))
        phi = np.where(np.abs(np.cos(phi)) > 1e-12, phi + np.where(np.isfinite(d), d, 0), phi)
    return phi


class Mercator(Proj):
    name = 'mercator'

    def setup(self):
        sp = self.parallels[0] if self.parallels else 0.0
        self.k = self.k0 * _msfn(sp * D2R, self.e)

    def _fwd(self, phi, lam):
        phi = np.clip(phi, -89.5 * D2R, 89.5 * D2R)
        return self.a * self.k * lam, -self.a * self.k * np.log(_tsfn(phi, self.e))

    def _inv(self, x, y):
        return _phi_from_t(np.exp(-y / (self.a * self.k)), self.e), x / (self.a * self.k)


class TranMerc(Proj):
    """The transverse Mercator on the ellipsoid by Krüger's series to the
    fourth power of the third flattening (mm within a UTM zone)."""
    name = 'tranmerc'

    def setup(self):
        a, e = self.a, self.e
        f = 1 - math.sqrt(1 - e * e)
        n = f / (2 - f)
        self.n = n
        self.A = a / (1 + n) * (1 + n ** 2 / 4 + n ** 4 / 64)
        self.al = [n / 2 - 2 * n ** 2 / 3 + 5 * n ** 3 / 16 + 41 * n ** 4 / 180, 13 * n ** 2 / 48 - 3 * n ** 3 / 5 + 557 * n ** 4 / 1440,
                   61 * n ** 3 / 240 - 103 * n ** 4 / 140, 49561 * n ** 4 / 161280]
        self.be = [n / 2 - 2 * n ** 2 / 3 + 37 * n ** 3 / 96 - n ** 4 / 360, n ** 2 / 48 + n ** 3 / 15 - 437 * n ** 4 / 1440,
                   17 * n ** 3 / 480 - 37 * n ** 4 / 840, 4397 * n ** 4 / 161280]
        self.y0 = self._northing(self.lat0 * D2R, 0.0)[1] if self.lat0 else 0.0

    def _northing(self, phi, lam):
        e = self.e
        s = np.sin(phi)
        t = np.sinh(np.arctanh(s) - e * np.arctanh(e * s)) if e else np.tan(phi)
        xi = np.arctan2(t, np.cos(lam))
        eta = np.arctanh(np.sin(lam) / np.sqrt(1 + t * t))
        X, Y = xi.copy() if isinstance(xi, np.ndarray) else xi, eta.copy() if isinstance(eta, np.ndarray) else eta
        for j, al in enumerate(self.al, 1):
            X = X + al * np.sin(2 * j * xi) * np.cosh(2 * j * eta)
            Y = Y + al * np.cos(2 * j * xi) * np.sinh(2 * j * eta)
        return self.k0 * self.A * Y, self.k0 * self.A * X

    def _fwd(self, phi, lam):
        x, y = self._northing(phi, lam)
        return x, y - self.y0

    def _inv(self, x, y):
        e = self.e
        xi = (y + self.y0) / (self.k0 * self.A)
        eta = x / (self.k0 * self.A)
        X, Y = xi, eta
        for j, b in enumerate(self.be, 1):
            X = X - b * np.sin(2 * j * xi) * np.cosh(2 * j * eta)
            Y = Y - b * np.cos(2 * j * xi) * np.sinh(2 * j * eta)
        chi = np.arcsin(np.sin(X) / np.cosh(Y))
        lam = np.arctan2(np.sinh(Y), np.cos(X))
        # the conformal latitude chi back to the geodetic latitude, by Newton on tau = tan(phi)
        tau_p = np.tan(chi)
        tau = tau_p.copy() if isinstance(tau_p, np.ndarray) else tau_p
        if e:
            for _ in range(8):
                sig = np.sinh(e * np.arctanh(e * tau / np.sqrt(1 + tau * tau)))
                tp = tau * np.sqrt(1 + sig * sig) - sig * np.sqrt(1 + tau * tau)
                d = (tau_p - tp) / np.sqrt(1 + tp * tp) * (1 + (1 - e * e) * tau * tau) / ((1 - e * e) * np.sqrt(1 + tau * tau))
                tau = tau + d
                if np.all(np.abs(d) < 1e-14):
                    break
        return np.arctan(tau), lam


class LambertConic(Proj):
    """Lambert's conformal conic with one or two standard parallels."""
    name = 'lambert'
    conic = True

    def setup(self):
        e = self.e
        p = self.parallels or [self.lat0]
        p1 = p[0] * D2R
        p2 = (p[1] if len(p) > 1 else p[0]) * D2R
        m1, m2 = _msfn(p1, e), _msfn(p2, e)
        t1, t2 = _tsfn(p1, e), _tsfn(p2, e)
        self.nn = math.sin(p1) if abs(p1 - p2) < 1e-12 else (math.log(m1) - math.log(m2)) / (math.log(t1) - math.log(t2))
        self.F = m1 / (self.nn * t1 ** self.nn)
        self.rho0 = self.a * self.F * _tsfn(self.lat0 * D2R, e) ** self.nn * self.k0

    def _fwd(self, phi, lam):
        rho = self.a * self.F * _tsfn(phi, self.e) ** self.nn * self.k0
        th = self.nn * lam
        return rho * np.sin(th), self.rho0 - rho * np.cos(th)

    def _inv(self, x, y):
        n = self.nn
        dy = self.rho0 - y
        rho = np.sign(n) * np.hypot(x, dy)
        th = np.arctan2(np.sign(n) * x, np.sign(n) * dy)
        t = (rho / (self.a * self.F * self.k0)) ** (1 / n)
        return _phi_from_t(t, self.e), th / n


class AlbersConic(Proj):
    """Albers' equal-area conic."""
    name = 'eqaconic'
    conic = True

    def setup(self):
        e = self.e
        p = self.parallels or [15.0, 75.0]
        p1, p2 = p[0] * D2R, (p[1] if len(p) > 1 else p[0]) * D2R
        m1, m2 = _msfn(p1, e), _msfn(p2, e)
        q1, q2 = _q(p1, e), _q(p2, e)
        self.nn = math.sin(p1) if abs(p1 - p2) < 1e-12 else (m1 * m1 - m2 * m2) / (q2 - q1)
        self.C = m1 * m1 + self.nn * q1
        self.rho0 = self.a * math.sqrt(max(self.C - self.nn * _q(self.lat0 * D2R, e), 0)) / self.nn
        self.qp = _q(math.pi / 2, e)

    def _fwd(self, phi, lam):
        rho = self.a * np.sqrt(np.maximum(self.C - self.nn * _q(phi, self.e), 0)) / self.nn
        th = self.nn * lam
        return rho * np.sin(th), self.rho0 - rho * np.cos(th)

    def _inv(self, x, y):
        n = self.nn
        dy = self.rho0 - y
        rho = np.hypot(x, dy)
        th = np.arctan2(np.sign(n) * x, np.sign(n) * dy)
        q = (self.C - (rho * n / self.a) ** 2) / n
        beta = np.arcsin(np.clip(q / self.qp, -1, 1))
        return _lat_from_authalic(beta, self.e), th / n


class EqdConic(Proj):
    """The equidistant conic (on the sphere of the semimajor axis)."""
    name = 'eqdconic'
    conic = True

    def setup(self):
        p = self.parallels or [15.0, 75.0]
        p1, p2 = p[0] * D2R, (p[1] if len(p) > 1 else p[0]) * D2R
        self.nn = math.sin(p1) if abs(p1 - p2) < 1e-12 else (math.cos(p1) - math.cos(p2)) / (p2 - p1)
        self.G = math.cos(p1) / self.nn + p1
        self.rho0 = self.a * (self.G - self.lat0 * D2R)

    def _fwd(self, phi, lam):
        rho = self.a * (self.G - phi)
        th = self.nn * lam
        return rho * np.sin(th), self.rho0 - rho * np.cos(th)

    def _inv(self, x, y):
        n = self.nn
        dy = self.rho0 - y
        rho = np.sign(n) * np.hypot(x, dy)
        th = np.arctan2(np.sign(n) * x, np.sign(n) * dy)
        return self.G - rho / self.a, th / n


class Azimuthal(Proj):
    """The azimuthal projections on the sphere of the semimajor axis, about
    the origin: orthographic, stereographic, gnomonic, equidistant and
    Lambert's equal-area (that one on the ellipsoid too, for the polar and
    oblique aspects through the authalic latitude)."""
    kind = 'ortho'

    def setup(self):
        self.p0 = self.lat0 * D2R
        self.s0, self.c0 = math.sin(self.p0), math.cos(self.p0)
        if self.kind == 'eqaazim' and self.e:
            e = self.e
            self.qp = _q(math.pi / 2, e)
            self.Rq = self.a * math.sqrt(self.qp / 2)
            b0 = math.asin(_q(self.p0, e) / self.qp)
            self.sb0, self.cb0 = math.sin(b0), math.cos(b0)
            self.D = self.a * _msfn(self.p0, e) / (self.Rq * self.cb0) if abs(self.cb0) > 1e-12 else 1.0

    def _cosc(self, phi, lam):
        return self.s0 * np.sin(phi) + self.c0 * np.cos(phi) * np.cos(lam)

    def visible(self, lat, lon):
        if self.kind in ('ortho', 'gnomonic'):
            c = self._cosc(np.asarray(lat, float) * D2R, self.dlon(lon) * D2R)
            return c >= (0 if self.kind == 'ortho' else 1e-6)
        if self.kind == 'stereo':
            c = self._cosc(np.asarray(lat, float) * D2R, self.dlon(lon) * D2R)
            return c > -0.99
        return np.ones(np.shape(lat), bool)

    def _fwd(self, phi, lam):
        a, k = self.a, self.kind
        if k == 'eqaazim' and self.e:
            beta = np.arcsin(np.clip(_q(phi, self.e) / self.qp, -1, 1))
            B = self.Rq * np.sqrt(2 / (1 + self.sb0 * np.sin(beta) + self.cb0 * np.cos(beta) * np.cos(lam)))
            x = B * self.D * np.cos(beta) * np.sin(lam)
            y = (B / self.D) * (self.cb0 * np.sin(beta) - self.sb0 * np.cos(beta) * np.cos(lam))
            return x, y
        cosc = self._cosc(phi, lam)
        if k == 'ortho':
            kk = np.ones_like(cosc)
        elif k == 'stereo':
            kk = 2 * self.k0 / (1 + cosc)
        elif k == 'gnomonic':
            kk = 1 / cosc
        elif k == 'eqaazim':
            kk = np.sqrt(2 / (1 + cosc))
        else:   # eqdazim
            c = np.arccos(np.clip(cosc, -1, 1))
            kk = np.where(c > 1e-12, c / np.sin(np.where(c > 1e-12, c, 1)), 1.0)
        x = a * kk * np.cos(phi) * np.sin(lam)
        y = a * kk * (self.c0 * np.sin(phi) - self.s0 * np.cos(phi) * np.cos(lam))
        return x, y

    def _inv(self, x, y):
        a, k = self.a, self.kind
        if k == 'eqaazim' and self.e:
            rho = np.hypot(x / self.D, self.D * y)
            ce = 2 * np.arcsin(np.clip(rho / (2 * self.Rq), -1, 1))
            with np.errstate(invalid='ignore', divide='ignore'):
                sb = np.where(rho > 0, np.cos(ce) * self.sb0 + self.D * y * np.sin(ce) * self.cb0 / rho, self.sb0)
            beta = np.arcsin(np.clip(sb, -1, 1))
            lam = np.arctan2(x * np.sin(ce), self.D * rho * self.cb0 * np.cos(ce) - self.D * self.D * y * self.sb0 * np.sin(ce))
            return _lat_from_authalic(beta, self.e), lam
        rho = np.hypot(x, y)
        if k == 'ortho':
            c = np.arcsin(np.clip(rho / a, -1, 1))
        elif k == 'stereo':
            c = 2 * np.arctan(rho / (2 * a * self.k0))
        elif k == 'gnomonic':
            c = np.arctan(rho / a)
        elif k == 'eqaazim':
            c = 2 * np.arcsin(np.clip(rho / (2 * a), -1, 1))
        else:
            c = rho / a
        sc, cc = np.sin(c), np.cos(c)
        with np.errstate(invalid='ignore', divide='ignore'):
            phi = np.where(rho > 0, np.arcsin(np.clip(cc * self.s0 + y * sc * self.c0 / np.where(rho > 0, rho, 1), -1, 1)), self.p0)
        lam = np.arctan2(x * sc, rho * self.c0 * cc - y * self.s0 * sc)
        return phi, lam


def _azimuthal(kind):
    return type(kind, (Azimuthal,), {'kind': kind, 'name': kind})


class PolarStereo(Proj):
    """The polar stereographic on the ellipsoid (UPS), with k0 at the pole."""
    name = 'ups'

    def setup(self):
        self.south = self.lat0 < 0
        e = self.e
        self.kk = 2 * self.a * self.k0 / math.sqrt((1 + e) ** (1 + e) * (1 - e) ** (1 - e)) if e else 2 * self.a * self.k0

    def _fwd(self, phi, lam):
        if self.south:
            phi, lam = -phi, -lam
        rho = self.kk * _tsfn(phi, self.e)
        x, y = rho * np.sin(lam), -rho * np.cos(lam)
        return (-x, -y) if self.south else (x, y)

    def _inv(self, x, y):
        if self.south:
            x, y = -x, -y
        rho = np.hypot(x, y)
        phi = _phi_from_t(rho / self.kk, self.e)
        lam = np.arctan2(x, -y)
        return (-phi, -lam) if self.south else (phi, lam)


class Sinusoid(Proj):
    name = 'sinusoid'

    def _fwd(self, phi, lam):
        return self.a * lam * np.cos(phi), self.a * phi

    def _inv(self, x, y):
        phi = y / self.a
        return phi, x / (self.a * np.cos(phi))


class Mollweide(Proj):
    name = 'mollweid'

    def _theta(self, phi):
        th = phi.copy() if isinstance(phi, np.ndarray) else np.array(phi, float)
        for _ in range(30):
            d = -(2 * th + np.sin(2 * th) - math.pi * np.sin(phi)) / (2 + 2 * np.cos(2 * th))
            d = np.where(np.isfinite(d), d, 0)
            th = th + d
            if np.all(np.abs(d) < 1e-13):
                break
        return th

    def _fwd(self, phi, lam):
        th = self._theta(phi)
        return self.a * 2 * math.sqrt(2) / math.pi * lam * np.cos(th), self.a * math.sqrt(2) * np.sin(th)

    def _inv(self, x, y):
        th = np.arcsin(np.clip(y / (self.a * math.sqrt(2)), -1, 1))
        phi = np.arcsin(np.clip((2 * th + np.sin(2 * th)) / math.pi, -1, 1))
        return phi, math.pi * x / (2 * math.sqrt(2) * self.a * np.cos(th))


class Hammer(Proj):
    name = 'hammer'

    def _fwd(self, phi, lam):
        d = np.sqrt(1 + np.cos(phi) * np.cos(lam / 2))
        return self.a * 2 * math.sqrt(2) * np.cos(phi) * np.sin(lam / 2) / d, self.a * math.sqrt(2) * np.sin(phi) / d

    def _inv(self, x, y):
        x, y = x / self.a, y / self.a
        z = np.sqrt(1 - (x / 4) ** 2 - (y / 2) ** 2)
        return np.arcsin(np.clip(z * y, -1, 1)), 2 * np.arctan2(z * x, 2 * (2 * z * z - 1))


# Robinson's table: per 5 degrees of latitude, the length of the parallel and its distance from the equator
_ROB = np.array([[1.0000, 0.0000], [0.9986, 0.0620], [0.9954, 0.1240], [0.9900, 0.1860], [0.9822, 0.2480], [0.9730, 0.3100],
                 [0.9600, 0.3720], [0.9427, 0.4340], [0.9216, 0.4958], [0.8962, 0.5571], [0.8679, 0.6176], [0.8350, 0.6769],
                 [0.7986, 0.7346], [0.7597, 0.7903], [0.7186, 0.8435], [0.6732, 0.8936], [0.6213, 0.9394], [0.5722, 0.9761],
                 [0.5322, 1.0000]])


class Robinson(Proj):
    name = 'robinson'

    def _fwd(self, phi, lam):
        from scipy.interpolate import CubicSpline
        lat = np.abs(phi * R2D)
        knots = np.arange(0, 91, 5.0)
        X = CubicSpline(knots, _ROB[:, 0])(np.clip(lat, 0, 90))
        Y = CubicSpline(knots, _ROB[:, 1])(np.clip(lat, 0, 90))
        return self.a * 0.8487 * X * lam, self.a * 1.3523 * Y * np.sign(phi)

    def _inv(self, x, y):
        from scipy.interpolate import CubicSpline
        knots = np.arange(0, 91, 5.0)
        Yt = np.clip(np.abs(y) / (self.a * 1.3523), 0, 1)
        lat = CubicSpline(_ROB[:, 1], knots)(Yt)
        # Newton on the forward spline, so that the inverse undoes the forward
        fy = CubicSpline(knots, _ROB[:, 1])
        dfy = fy.derivative()
        for _ in range(4):
            lat = np.clip(lat - (fy(lat) - Yt) / np.where(dfy(lat) != 0, dfy(lat), 1), 0, 90)
        X = CubicSpline(knots, _ROB[:, 0])(lat)
        return np.sign(y) * lat * D2R, x / (self.a * 0.8487 * X)


class EqualEarth(Proj):
    name = 'equalearth'
    A1, A2, A3, A4 = 1.340264, -0.081106, 0.000893, 0.003796

    def _fwd(self, phi, lam):
        th = np.arcsin(math.sqrt(3) / 2 * np.sin(phi))
        t2 = th * th
        t6 = t2 ** 3
        x = 2 * math.sqrt(3) * lam * np.cos(th) / (3 * (9 * self.A4 * t6 * t2 + 7 * self.A3 * t6 + 3 * self.A2 * t2 + self.A1))
        y = th * (self.A1 + self.A2 * t2 + self.A3 * t6 + self.A4 * t6 * t2)
        return self.a * x, self.a * y

    def _inv(self, x, y):
        x, y = x / self.a, y / self.a
        th = y.copy() if isinstance(y, np.ndarray) else np.array(y, float)
        for _ in range(20):
            t2 = th * th
            t6 = t2 ** 3
            f = th * (self.A1 + self.A2 * t2 + self.A3 * t6 + self.A4 * t6 * t2) - y
            fp = self.A1 + 3 * self.A2 * t2 + 7 * self.A3 * t6 + 9 * self.A4 * t6 * t2
            d = f / fp
            th = th - d
            if np.all(np.abs(d) < 1e-13):
                break
        t2 = th * th
        t6 = t2 ** 3
        lam = 3 * x * (self.A1 + 3 * self.A2 * t2 + 7 * self.A3 * t6 + 9 * self.A4 * t6 * t2) / (2 * math.sqrt(3) * np.cos(th))
        return np.arcsin(np.clip(2 * np.sin(th) / math.sqrt(3), -1, 1)), lam


PROJECTIONS = {
    'eqdcylin': EqdCylin, 'pcarree': EqdCylin, 'miller': Miller, 'eqacylin': EqaCylin, 'mercator': Mercator, 'tranmerc': TranMerc,
    'utm': TranMerc, 'lambert': LambertConic, 'lambertstd': LambertConic, 'eqaconic': AlbersConic, 'eqaconicstd': AlbersConic,
    'eqdconic': EqdConic, 'eqdconicstd': EqdConic, 'ortho': _azimuthal('ortho'), 'stereo': _azimuthal('stereo'),
    'gnomonic': _azimuthal('gnomonic'), 'eqdazim': _azimuthal('eqdazim'), 'eqaazim': _azimuthal('eqaazim'), 'ups': PolarStereo,
    'sinusoid': Sinusoid, 'mollweid': Mollweide, 'hammer': Hammer, 'robinson': Robinson, 'equalearth': EqualEarth,
}

ELLIPSOIDS = {
    # name: (code, a in m, inverse flattening (0 for a sphere), the full name)
    'wgs84': (7030, 6378137.0, 298.257223563, 'World Geodetic System 1984'),
    'grs80': (7019, 6378137.0, 298.257222101, 'Geodetic Reference System 1980'),
    'wgs72': (7043, 6378135.0, 298.26, 'World Geodetic System 1972'),
    'international': (7022, 6378388.0, 297.0, 'International 1924'),
    'clarke66': (7008, 6378206.4, 294.978698213898, 'Clarke 1866'),
    'clarke80': (7012, 6378249.145, 293.465, 'Clarke 1880 (RGS)'),
    'bessel': (7004, 6377397.155, 299.1528128, 'Bessel 1841'),
    'airy1830': (7001, 6377563.396, 299.3249646, 'Airy 1830'),
    'krasovsky': (7024, 6378245.0, 298.3, 'Krassowsky 1940'),
    'everest': (7015, 6377276.345, 300.8017, 'Everest 1830 (1937 Adjustment)'),
    'grs67': (7036, 6378160.0, 298.247167427, 'Geodetic Reference System 1967'),
}
ALIASES = {'wgs 84': 'wgs84', 'grs 80': 'grs80', 'grs1980': 'grs80', 'hayford': 'international', 'international1924': 'international',
           'clarke1866': 'clarke66', 'bessel1841': 'bessel', 'airy': 'airy1830', 'krassowsky': 'krasovsky', 'krasovsky1940': 'krasovsky',
           'everest1830': 'everest'}
SPHERES = {'earth': 6371000.0, 'sun': 695700000.0, 'moon': 1737400.0, 'mercury': 2439700.0, 'venus': 6051800.0, 'mars': 3389500.0,
           'jupiter': 69911000.0, 'saturn': 58232000.0, 'uranus': 25362000.0, 'neptune': 24622000.0, 'pluto': 1188300.0, 'unit sphere': 1.0}


def ellipsoid_ae(name):
    """(a, e, inverse flattening, code, full name) of a named ellipsoid, in meters."""
    k = name.lower().replace('-', ' ').strip()
    k = ALIASES.get(k, ALIASES.get(k.replace(' ', ''), k.replace(' ', '') if k.replace(' ', '') in ELLIPSOIDS else k))
    if k in ELLIPSOIDS:
        code, a, inv, full = ELLIPSOIDS[k]
        f = 1 / inv
        return a, math.sqrt(f * (2 - f)), inv, code, full
    return None


def epsg_ellipsoid(code):
    for k, (c, a, inv, full) in ELLIPSOIDS.items():
        if c == code:
            return k
    return None


# EPSG projected systems known without PROJ: (name, projection, ellipsoid, parameters)
def epsg(code):
    W, G = 'wgs84', 'grs80'
    if 32601 <= code <= 32660 or 32701 <= code <= 32760:
        z = code % 100
        south = code > 32700
        return (f'WGS 84 / UTM zone {z}{"S" if south else "N"}', 'tranmerc', W,
                dict(lat0=0.0, lon0=-183.0 + 6 * z, k0=0.9996, fe=500000.0, fn=10000000.0 if south else 0.0), 'EPSG:4326')
    if 25828 <= code <= 25838:
        z = code - 25800
        return (f'ETRS89 / UTM zone {z}N', 'tranmerc', G, dict(lat0=0.0, lon0=-183.0 + 6 * z, k0=0.9996, fe=500000.0, fn=0.0), 'EPSG:4258')
    sweref = {3007: ('12 00', 12.0), 3008: ('13 30', 13.5), 3009: ('15 00', 15.0), 3010: ('16 30', 16.5), 3011: ('18 00', 18.0),
              3012: ('14 15', 14.25), 3013: ('15 45', 15.75), 3014: ('17 15', 17.25), 3015: ('18 45', 18.75), 3016: ('20 15', 20.25),
              3017: ('21 45', 21.75), 3018: ('23 15', 23.25)}
    table = {
        3006: ('SWEREF99 TM', 'tranmerc', G, dict(lat0=0.0, lon0=15.0, k0=0.9996, fe=500000.0, fn=0.0), 'EPSG:4619'),
        3021: ('RT90 2.5 gon V', 'tranmerc', 'bessel', dict(lat0=0.0, lon0=15.0 + 48 / 60 + 29.8 / 3600, k0=1.0, fe=1500000.0, fn=0.0), 'EPSG:4124'),
        3857: ('WGS 84 / Pseudo-Mercator', 'mercator', 'sphere6378137', dict(lat0=0.0, lon0=0.0, k0=1.0), 'EPSG:4326'),
        3395: ('WGS 84 / World Mercator', 'mercator', W, dict(lat0=0.0, lon0=0.0, k0=1.0), 'EPSG:4326'),
        3035: ('ETRS89-extended / LAEA Europe', 'eqaazim', G, dict(lat0=52.0, lon0=10.0, fe=4321000.0, fn=3210000.0), 'EPSG:4258'),
        3034: ('ETRS89-extended / LCC Europe', 'lambert', G, dict(lat0=52.0, lon0=10.0, parallels=[35.0, 65.0], fe=4000000.0, fn=2800000.0), 'EPSG:4258'),
        2154: ('RGF93 v1 / Lambert-93', 'lambert', G, dict(lat0=46.5, lon0=3.0, parallels=[49.0, 44.0], fe=700000.0, fn=6600000.0), 'EPSG:4171'),
        27700: ('OSGB36 / British National Grid', 'tranmerc', 'airy1830', dict(lat0=49.0, lon0=-2.0, k0=0.9996012717, fe=400000.0, fn=-100000.0), 'EPSG:4277'),
        5070: ('NAD83 / Conus Albers', 'eqaconic', G, dict(lat0=23.0, lon0=-96.0, parallels=[29.5, 45.5]), 'EPSG:4269'),
        32661: ('WGS 84 / UPS North (N,E)', 'ups', W, dict(lat0=90.0, lon0=0.0, k0=0.994, fe=2000000.0, fn=2000000.0), 'EPSG:4326'),
        32761: ('WGS 84 / UPS South (N,E)', 'ups', W, dict(lat0=-90.0, lon0=0.0, k0=0.994, fe=2000000.0, fn=2000000.0), 'EPSG:4326'),
    }
    for c, (nm, lon0) in sweref.items():
        table[c] = (f'SWEREF99 {nm}', 'tranmerc', G, dict(lat0=0.0, lon0=lon0, k0=1.0, fe=150000.0, fn=0.0), 'EPSG:4619')
    return table.get(code)


def make(name, a=1.0, e=0.0, **kw):
    return PROJECTIONS[name](a=a, e=e, **kw)


# ---- geodesy ---------------------------------------------------------------------------------------------------

def gc_inverse(lat1, lon1, lat2, lon2):
    """Great-circle distance (radians of arc) and azimuth (radians) on the sphere."""
    p1, p2 = lat1 * D2R, lat2 * D2R
    dl = (lon2 - lon1) * D2R
    h = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    d = 2 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))
    az = np.arctan2(np.sin(dl) * np.cos(p2), np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl))
    return d, az


def gc_direct(lat1, lon1, d, az):
    """The point at arc d (radians) along azimuth az (radians) on the sphere."""
    p1 = lat1 * D2R
    p2 = np.arcsin(np.clip(np.sin(p1) * np.cos(d) + np.cos(p1) * np.sin(d) * np.cos(az), -1, 1))
    l2 = lon1 * D2R + np.arctan2(np.sin(az) * np.sin(d) * np.cos(p1), np.cos(d) - np.sin(p1) * np.sin(p2))
    return p2 * R2D, l2 * R2D


def vincenty_inverse(lat1, lon1, lat2, lon2, a, e):
    """Geodesic distance and forward azimuth (radians) on the ellipsoid, by
    Vincenty's iteration; nearly antipodal points where it does not converge
    take the great circle on the authalic sphere."""
    lat1, lon1, lat2, lon2 = np.broadcast_arrays(*(np.asarray(v, float) for v in (lat1, lon1, lat2, lon2)))
    shape = lat1.shape
    out_s = np.empty(shape)
    out_a = np.empty(shape)
    f = 1 - math.sqrt(1 - e * e)
    b = a * (1 - f)
    for idx in np.ndindex(shape):
        p1, p2 = lat1[idx] * D2R, lat2[idx] * D2R
        L = ((lon2[idx] - lon1[idx] + 180) % 360 - 180) * D2R
        if not all(map(math.isfinite, (p1, p2, L))):
            out_s[idx] = out_a[idx] = math.nan
            continue
        U1 = math.atan((1 - f) * math.tan(p1))
        U2 = math.atan((1 - f) * math.tan(p2))
        sU1, cU1, sU2, cU2 = math.sin(U1), math.cos(U1), math.sin(U2), math.cos(U2)
        lam = L
        ok = False
        for _ in range(200):
            sl, cl = math.sin(lam), math.cos(lam)
            ss = math.hypot(cU2 * sl, cU1 * sU2 - sU1 * cU2 * cl)
            if ss == 0:
                out_s[idx], out_a[idx] = 0.0, 0.0
                ok = None
                break
            cs = sU1 * sU2 + cU1 * cU2 * cl
            sig = math.atan2(ss, cs)
            sa = cU1 * cU2 * sl / ss
            c2a = 1 - sa * sa
            c2sm = cs - 2 * sU1 * sU2 / c2a if c2a != 0 else 0.0
            C = f / 16 * c2a * (4 + f * (4 - 3 * c2a))
            prev = lam
            lam = L + (1 - C) * f * sa * (sig + C * ss * (c2sm + C * cs * (-1 + 2 * c2sm * c2sm)))
            if abs(lam - prev) < 1e-12:
                ok = True
                break
        if ok is None:
            continue
        if not ok:
            R = authalic_radius(a, e)
            d, az = gc_inverse(lat1[idx], lon1[idx], lat2[idx], lon2[idx])
            out_s[idx], out_a[idx] = R * float(d), float(az)
            continue
        u2 = c2a * (a * a - b * b) / (b * b)
        A = 1 + u2 / 16384 * (4096 + u2 * (-768 + u2 * (320 - 175 * u2)))
        B = u2 / 1024 * (256 + u2 * (-128 + u2 * (74 - 47 * u2)))
        ds = B * ss * (c2sm + B / 4 * (cs * (-1 + 2 * c2sm * c2sm) - B / 6 * c2sm * (-3 + 4 * ss * ss) * (-3 + 4 * c2sm * c2sm)))
        out_s[idx] = b * A * (sig - ds)
        out_a[idx] = math.atan2(cU2 * math.sin(lam), cU1 * sU2 - sU1 * cU2 * math.cos(lam))
    return out_s, out_a


def vincenty_direct(lat1, lon1, s, az, a, e):
    """The point at geodesic distance s along azimuth az (radians) on the ellipsoid, by Vincenty."""
    lat1, lon1, s, az = np.broadcast_arrays(*(np.asarray(v, float) for v in (lat1, lon1, s, az)))
    shape = lat1.shape
    olat, olon = np.empty(shape), np.empty(shape)
    f = 1 - math.sqrt(1 - e * e)
    b = a * (1 - f)
    for idx in np.ndindex(shape):
        p1, a1, dist = lat1[idx] * D2R, az[idx], s[idx]
        U1 = math.atan((1 - f) * math.tan(p1))
        s1 = math.atan2(math.tan(U1), math.cos(a1))
        sa = math.cos(U1) * math.sin(a1)
        c2a = 1 - sa * sa
        u2 = c2a * (a * a - b * b) / (b * b)
        A = 1 + u2 / 16384 * (4096 + u2 * (-768 + u2 * (320 - 175 * u2)))
        B = u2 / 1024 * (256 + u2 * (-128 + u2 * (74 - 47 * u2)))
        sig = dist / (b * A)
        for _ in range(200):
            c2sm = math.cos(2 * s1 + sig)
            ss, cs = math.sin(sig), math.cos(sig)
            ds = B * ss * (c2sm + B / 4 * (cs * (-1 + 2 * c2sm * c2sm) - B / 6 * c2sm * (-3 + 4 * ss * ss) * (-3 + 4 * c2sm * c2sm)))
            new = dist / (b * A) + ds
            if abs(new - sig) < 1e-12:
                sig = new
                break
            sig = new
        c2sm = math.cos(2 * s1 + sig)
        ss, cs = math.sin(sig), math.cos(sig)
        sU1, cU1 = math.sin(U1), math.cos(U1)
        t = sU1 * ss - cU1 * cs * math.cos(a1)
        p2 = math.atan2(sU1 * cs + cU1 * ss * math.cos(a1), (1 - f) * math.hypot(sa, t))
        lam = math.atan2(ss * math.sin(a1), cU1 * cs - sU1 * ss * math.cos(a1))
        C = f / 16 * c2a * (4 + f * (4 - 3 * c2a))
        L = lam - (1 - C) * f * sa * (sig + C * ss * (c2sm + C * cs * (-1 + 2 * c2sm * c2sm)))
        olat[idx] = p2 * R2D
        olon[idx] = lon1[idx] + L * R2D
    return olat, olon


def rhumb_inverse(lat1, lon1, lat2, lon2, a, e):
    """Rhumb-line distance and azimuth (radians) on the ellipsoid (a sphere when e = 0)."""
    p1, p2 = np.asarray(lat1, float) * D2R, np.asarray(lat2, float) * D2R
    dl = ((np.asarray(lon2, float) - np.asarray(lon1, float) + 180) % 360 - 180) * D2R
    psi = lambda p: -np.log(_tsfn(np.clip(p, -89.999999 * D2R, 89.999999 * D2R), e))
    dpsi = psi(p2) - psi(p1)
    az = np.arctan2(dl, dpsi)
    dm = meridian_arc(p2, a, e) - meridian_arc(p1, a, e)
    with np.errstate(invalid='ignore', divide='ignore'):
        nu = a / np.sqrt(1 - (e * np.sin(p1)) ** 2)
        d = np.where(np.abs(np.cos(az)) > 1e-12, dm / np.cos(az), np.abs(dl) * nu * np.cos(p1))
    return np.abs(d), az % (2 * math.pi)


def rhumb_direct(lat1, lon1, d, az, a, e):
    p1 = np.asarray(lat1, float) * D2R
    m2 = meridian_arc(p1, a, e) + d * np.cos(az)
    # the latitude whose meridian arc is m2, by Newton
    p2 = m2 / a
    for _ in range(20):
        g = meridian_arc(p2, a, e) - m2
        dm = a * (1 - e * e) / (1 - (e * np.sin(p2)) ** 2) ** 1.5
        p2 = p2 - g / dm
    psi = lambda p: -np.log(_tsfn(p, e))
    with np.errstate(invalid='ignore', divide='ignore'):
        nu = a / np.sqrt(1 - (e * np.sin(p1)) ** 2)
        dl = np.where(np.abs(np.cos(az)) > 1e-12, np.tan(az) * (psi(p2) - psi(p1)), d * np.sin(az) / (nu * np.cos(p1)))
    return p2 * R2D, np.asarray(lon1, float) + dl * R2D


# ---- coordinates of the Earth: ECEF and local frames ------------------------------------------------------------------

def geodetic2ecef(lat, lon, h, a, e):
    p, l = np.asarray(lat, float) * D2R, np.asarray(lon, float) * D2R
    N = a / np.sqrt(1 - (e * np.sin(p)) ** 2)
    return ((N + h) * np.cos(p) * np.cos(l), (N + h) * np.cos(p) * np.sin(l), (N * (1 - e * e) + h) * np.sin(p))


def ecef2geodetic(x, y, z, a, e):
    """Latitude, longitude (degrees) and height, by Bowring's iteration from
    his first guess (to round-off in two or three steps)."""
    x, y, z = (np.asarray(v, float) for v in (x, y, z))
    e2 = e * e
    b = a * math.sqrt(1 - e2)
    ep2 = (a * a - b * b) / (b * b) if b else 0.0
    p = np.hypot(x, y)
    lon = np.arctan2(y, x)
    with np.errstate(invalid='ignore', divide='ignore'):
        th = np.arctan2(z * a, p * b) if b else np.zeros_like(p)
        lat = np.arctan2(z + ep2 * b * np.sin(th) ** 3, p - e2 * a * np.cos(th) ** 3)
        for _ in range(5):
            N = a / np.sqrt(1 - e2 * np.sin(lat) ** 2)
            h = np.where(np.abs(np.cos(lat)) > 1e-10, p / np.cos(lat) - N, np.abs(z) - b)
            lat = np.arctan2(z, p * (1 - e2 * N / (N + h)))
        N = a / np.sqrt(1 - e2 * np.sin(lat) ** 2)
        h = np.where(np.abs(np.cos(lat)) > 1e-10, p / np.cos(lat) - N, np.abs(z) - b)
    return lat * R2D, lon * R2D, h


def _enu_rot(lat0, lon0):
    p, l = np.asarray(lat0, float) * D2R, np.asarray(lon0, float) * D2R
    return np.sin(p), np.cos(p), np.sin(l), np.cos(l)


def ecef2enu_vec(dx, dy, dz, lat0, lon0):
    sp_, cp, sl, cl = _enu_rot(lat0, lon0)
    t = cl * dx + sl * dy
    return -sl * dx + cl * dy, -sp_ * t + cp * dz, cp * t + sp_ * dz


def enu2ecef_vec(e_, n, u, lat0, lon0):
    sp_, cp, sl, cl = _enu_rot(lat0, lon0)
    t = cp * u - sp_ * n
    return cl * t - sl * e_, sl * t + cl * e_, sp_ * u + cp * n


def enu2aer(e_, n, u):
    r = np.hypot(e_, n)
    return (np.arctan2(e_, n) * R2D) % 360, np.arctan2(u, r) * R2D, np.hypot(r, u)


def aer2enu(az, el, rng):
    a, e_ = np.asarray(az, float) * D2R, np.asarray(el, float) * D2R
    r = rng * np.cos(e_)
    return r * np.sin(a), r * np.cos(a), rng * np.sin(e_)
