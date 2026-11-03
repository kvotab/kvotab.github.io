"""datetime, duration and calendarDuration: arrays of points in time, of
lengths of time, and of lengths in calendar units (months and days, whose
length depends on where they start). They are value objects (vobj.py).

A datetime holds seconds since 1970-01-01 00:00:00: wall-clock time when
it has no time zone, UTC when it has one (its TimeZone turning them into
the zone's wall clock for display and for the calendar). NaT is NaN. A
duration holds seconds; a calendarDuration months, days and seconds.
Formats follow the language's letters (uuuu or yyyy, MM, MMM, dd, HH, mm,
ss, SSS, eee, a, ...)."""
import datetime as _dt
import math
import re
import time

import numpy as np

from . import bi
from ._util import err, nargchk, darr, out, num, ival, opt_str, is_str, sval
from ..values import MError, Char, Str, Cell, Struct, F64, numel, shape_of, class_of, py_str, text_list
from ..vobj import VObj, _2d
from .timefun import _days_from_civil, _civil_from_days, _MONTHS, _DAYS, _EPOCH, _month_days

DAY = 86400.0
FULL = 'dd-MMM-uuuu HH:mm:ss'
DATE = 'dd-MMM-uuuu'


def _bcast(*arrs):
    try:
        return np.broadcast_arrays(*arrs)
    except ValueError:
        raise MError('MATLAB:sizeDimensionsMustMatch', 'Arrays have incompatible sizes for this operation.')


# ---- time zones --------------------------------------------------------------------------------------------

_FIXED = re.compile(r'^([+-])(\d{2}):?(\d{2})$')


def _zone(tz):
    """A function giving the zone's offset (seconds east of UTC) at UTC seconds."""
    if tz in ('', None):
        return None
    if tz.upper() in ('UTC', 'GMT', 'Z', 'UTCLEAPSECONDS'):
        return lambda s: np.zeros(np.shape(s))
    m = _FIXED.match(tz)
    if m:
        off = (1 if m.group(1) == '+' else -1) * (int(m.group(2)) * 3600 + int(m.group(3)) * 60)
        return lambda s: np.full(np.shape(s), float(off))
    if tz.lower() == 'local':
        off = -time.timezone if not time.daylight else -time.altzone
        return lambda s: np.full(np.shape(s), float(off))
    try:
        from zoneinfo import ZoneInfo
        z = ZoneInfo(tz)
    except Exception:
        z = _browser_zone(tz)
        if z is None:
            raise MError('MATLAB:datetime:UnknownTimeZone', f"'{tz}' is not a time zone known here: use 'UTC', an offset such as '+01:00', or a zone name such as 'Europe/Stockholm'.")
        return z

    def off(s):
        s = np.asarray(s, float)
        res = np.zeros(s.shape)
        for i, x in np.ndenumerate(s):
            if np.isfinite(x):
                d = _dt.datetime.fromtimestamp(float(x), tz=_dt.timezone.utc).astimezone(z)
                res[i] = d.utcoffset().total_seconds()
        return res
    return off


def _browser_zone(tz):
    """In the page, where Python has no zone database: the offset from the
    browser's (Intl.DateTimeFormat), the wall clock it gives for each
    instant minus the instant. None when the browser does not know the zone."""
    import sys
    if sys.platform != 'emscripten':
        return None
    import js
    opts = js.Object.new()
    opts.timeZone = tz
    opts.hourCycle = 'h23'
    for k in ('year', 'month', 'day', 'hour', 'minute', 'second'):
        setattr(opts, k, 'numeric')
    try:
        fmt = js.Intl.DateTimeFormat.new('en-US', opts)
    except Exception:
        return None
    seen = {}

    def wall_of(t):
        parts = {p.type: p.value for p in fmt.formatToParts(js.Date.new(t * 1000.0))}
        days = _days_from_civil(int(parts['year']), int(parts['month']), int(parts['day']))
        return days * DAY + int(parts['hour']) * 3600 + int(parts['minute']) * 60 + int(parts['second'])

    def off(s):
        s = np.asarray(s, float)
        res = np.zeros(s.shape)
        for i, x in np.ndenumerate(s):
            if np.isfinite(x):
                t = math.floor(x)
                if t not in seen:
                    seen[t] = float(wall_of(t) - t)
                res[i] = seen[t]
        return res
    return off


def _valid_tz(tz):
    _zone(tz)
    return tz


def _to_wall(a, tz):
    z = _zone(tz)
    return a if z is None else a + z(a)


def _from_wall(w, tz):
    z = _zone(tz)
    if z is None:
        return w
    guess = w - z(w)
    return w - z(guess)


# ---- the calendar ------------------------------------------------------------------------------------------

def _parts(w):
    """Year, month, day, hour, minute and second (with its fraction) of wall seconds (NaN stays NaN)."""
    w = np.asarray(w, float)
    ok = np.isfinite(w)
    ws = np.where(ok, w, 0.0)
    days = np.floor(ws / DAY)
    sod = ws - days * DAY
    # round away the last bits so that 59.9999999 seconds is 60, carried
    sod = np.round(sod, 6)
    carry = sod >= DAY
    days = days + carry
    sod = np.where(carry, sod - DAY, sod)
    y, mo, d = _civil_from_days(days.astype(np.int64))
    h = np.floor(sod / 3600)
    mi = np.floor((sod - h * 3600) / 60)
    s = sod - h * 3600 - mi * 60
    nan = np.where(ok, 1.0, np.nan)
    return (y * nan, mo * nan, d * nan, h * nan, mi * nan, s * nan)


def _compose(y, mo, d, h=0.0, mi=0.0, s=0.0):
    """Wall seconds from parts: months past 12 roll into years, days, hours,
    minutes and seconds past their ranges into the next."""
    y, mo, d, h, mi, s = _bcast(*[np.asarray(v, float) for v in (y, mo, d, h, mi, s)])
    ok = np.isfinite(y) & np.isfinite(mo) & np.isfinite(d) & np.isfinite(h) & np.isfinite(mi) & np.isfinite(s)
    yy, mm = np.where(ok, y, 1970), np.where(ok, mo, 1)
    yi = np.floor(yy) + np.floor_divide(np.floor(mm) - 1, 12)
    mi_ = np.mod(np.floor(mm) - 1, 12) + 1
    days = _days_from_civil(yi.astype(np.int64), mi_.astype(np.int64), 1).astype(float) + np.where(ok, d, 1) - 1
    r = days * DAY + np.where(ok, h, 0) * 3600 + np.where(ok, mi, 0) * 60 + np.where(ok, s, 0)
    return np.where(ok, r, np.nan)


def _add_months(w, months):
    """Wall seconds moved by whole months, the day kept (or the month's last day if it is shorter)."""
    y, mo, d, h, mi, s = _parts(w)
    months = np.asarray(months, float)
    t = (np.where(np.isfinite(mo), mo, 1) - 1) + months
    yy = np.where(np.isfinite(y), y, 1970) + np.floor(t / 12)
    mm = np.mod(t, 12) + 1
    ok = np.isfinite(w) & np.isfinite(months)
    last = _month_days(yy.astype(np.int64), np.where(np.isfinite(mm), mm, 1).astype(np.int64))
    dd = np.minimum(np.where(np.isfinite(d), d, 1), last)
    r = _compose(yy, mm, dd, h, mi, s)
    return np.where(ok, r, np.nan)


# ---- formats ---------------------------------------------------------------------------------------------

_TOK = re.compile(r"'([^']*)'|([A-Za-z])\2*|[^A-Za-z']")


def _tokens(fmt):
    """The format's pieces: ('lit', text) or (letter, count)."""
    out_ = []
    for m in _TOK.finditer(fmt):
        if m.group(1) is not None:
            out_.append(('lit', m.group(1) if m.group(1) else "'"))
        elif m.group(2):
            out_.append((m.group(2), len(m.group(0))))
        else:
            out_.append(('lit', m.group(0)))
    return out_


def _format(w, fmt, tz=''):
    """Each wall time in the format, 'NaT' for missing."""
    w = np.asarray(w, float)
    res = np.empty(w.shape, object)
    if w.size == 0:
        return res
    y, mo, d, h, mi, s = _parts(w)
    toks = _tokens(fmt)
    days = np.floor(np.where(np.isfinite(w), w, 0) / DAY)
    for idx in np.ndindex(w.shape):
        if not np.isfinite(w[idx]):
            res[idx] = 'NaT'
            continue
        Y, M, D, H, MI, S = (int(x[idx]) if k < 5 else float(x[idx]) for k, x in enumerate((y, mo, d, h, mi, s)))
        parts = []
        for c, n in toks:
            if c == 'lit':
                parts.append(n)
            elif c in 'yu':
                parts.append(f'{Y % 100:02d}' if n == 2 else (f'{Y:04d}' if n >= 3 and Y >= 0 else str(Y)))
            elif c in 'ML':
                parts.append(_MONTHS[M - 1] if n >= 4 else _MONTHS[M - 1][:3] if n == 3 else f'{M:02d}' if n == 2 else str(M))
            elif c == 'd':
                parts.append(f'{D:02d}' if n >= 2 else str(D))
            elif c == 'D':
                doy = int(days[idx] - _days_from_civil(Y, 1, 1)) + 1
                parts.append(f'{doy:0{n}d}')
            elif c in 'eE':
                wd = int((days[idx] + 4) % 7)          # 1970-01-01 was a Thursday
                name = _DAYS[wd]
                parts.append(name if n >= 4 else name[:3] if n == 3 or c == 'E' else str(wd + 1))
            elif c == 'H':
                parts.append(f'{H:02d}' if n >= 2 else str(H))
            elif c == 'h':
                hh = H % 12 or 12
                parts.append(f'{hh:02d}' if n >= 2 else str(hh))
            elif c == 'm':
                parts.append(f'{MI:02d}' if n >= 2 else str(MI))
            elif c == 's':
                parts.append(f'{int(S):02d}' if n >= 2 else str(int(S)))
            elif c == 'S':
                frac = S - int(S)
                parts.append(str(int(math.floor(round(frac, 9) * 10 ** n + 1e-6))).rjust(n, '0')[:n])
            elif c == 'a':
                parts.append('AM' if H < 12 else 'PM')
            elif c == 'Q':
                q = (M - 1) // 3 + 1
                parts.append(f'Q{q}' if n == 3 else f'{q}' if n <= 2 else ['1st', '2nd', '3rd', '4th'][q - 1] + ' quarter')
            elif c in 'zZxX':
                parts.append(tz or '')
            elif c == 'G':
                parts.append('AD' if Y > 0 else 'BC')
            else:
                parts.append(c * n)
        res[idx] = ''.join(parts)
    return res


def _check_format(fmt):
    for c, n in _tokens(fmt):
        if c != 'lit' and c not in 'yuMLdDeEHhmsSaQzZxXG':
            raise MError('MATLAB:datetime:UnsupportedSymbol', f"The format '{fmt}' has a letter, '{c}', that is not a date or time field.")
    return fmt


def _regex(fmt):
    """A regular expression reading text in the format, its groups named by field."""
    rx = []
    seen = set()
    for c, n in _tokens(fmt):
        if c == 'lit':
            rx.append(r'\s+' if n.isspace() else re.escape(n))
            continue
        name = {'y': 'y', 'u': 'y', 'M': 'M', 'L': 'M', 'd': 'd', 'D': 'D', 'H': 'H', 'h': 'h', 'm': 'm', 's': 's', 'S': 'S', 'a': 'a'}.get(c)
        if c in 'yu':
            pat = r'\d{2}' if n == 2 else r'[+-]?\d{4,}' if n >= 4 else r'[+-]?\d+'
        elif c in 'ML':
            pat = r'[A-Za-z]+' if n >= 4 else r'[A-Za-z]{3}' if n == 3 else r'\d{2}' if n == 2 else r'\d{1,2}'
        elif c == 'D':
            pat = r'\d{1,3}' if n < 3 else r'\d{3}'
        elif c in 'dHhms':
            pat = r'\d{2}' if n >= 2 else r'\d{1,2}'
        elif c == 'S':
            pat = r'\d{%d}' % n
        elif c == 'a':
            pat = r'[AaPp][Mm]'
        elif c in 'eE':
            pat = r'[A-Za-z]+'
        elif c in 'zZxX':
            pat = r'(?:Z|[+-]\d{2}:?\d{2}|[A-Za-z_/+-]+)'
        elif c == 'Q':
            pat = r'Q?\d'
        else:
            pat = re.escape(c * n)
        if name and name not in seen:
            rx.append(f'(?P<{name}>{pat})')
            seen.add(name)
        else:
            rx.append(pat)
    return '^' + ''.join(rx) + '$'


def _month_of(text):
    t = text.lower()
    for k, m in enumerate(_MONTHS):
        if m.lower() == t or m.lower()[:3] == t[:3] and len(t) == 3:
            return k + 1
    return None


def _parse(texts, fmt):
    """Wall seconds of each text in the format (NaN where one does not read), and whether all did."""
    rx = re.compile(_regex(fmt), re.I)
    res = np.full(len(texts), np.nan)
    ok_all = True
    for i, t in enumerate(texts):
        t = (t or '').strip()
        if t == '' or t.lower() == 'nat':
            continue
        m = rx.match(t)
        if not m:
            ok_all = False
            continue
        g = m.groupdict()
        try:
            y = int(g['y']) if g.get('y') else 1970
            if g.get('y') and len(g['y']) == 2:
                y = 2000 + y if y < 50 else 1900 + y      # two digits: 1950 to 2049
            M = g.get('M')
            mo = (int(M) if M.isdigit() else _month_of(M)) if M else 1
            dd = int(g['d']) if g.get('d') else 1
            if g.get('D') and not g.get('M'):
                mo, dd = 1, int(g['D'])
            H = int(g['H']) if g.get('H') else 0
            if g.get('h'):
                H = int(g['h']) % 12
            if g.get('a') and g['a'].lower() == 'pm':
                H = H % 12 + 12
            mi = int(g['m']) if g.get('m') else 0
            s = float(g['s']) if g.get('s') else 0.0
            if g.get('S'):
                s += float('0.' + g['S'])
            if mo is None or not 1 <= mo <= 12 or not 1 <= dd <= 31 or H > 24 or mi > 59 or s >= 61:
                raise ValueError
            if g.get('M') or g.get('d'):
                if dd > int(_month_days(np.int64(y), np.int64(mo))):
                    raise ValueError
        except (ValueError, TypeError):
            ok_all = False
            continue
        res[i] = float(_compose(y, mo, dd, H, mi, s))
    return res, ok_all


_AUTO = ["uuuu-MM-dd'T'HH:mm:ss.SSSSSS", "uuuu-MM-dd'T'HH:mm:ss.SSS", "uuuu-MM-dd'T'HH:mm:ss", "uuuu-MM-dd'T'HH:mm",
         'uuuu-MM-dd HH:mm:ss.SSSSSS', 'uuuu-MM-dd HH:mm:ss.SSS', 'uuuu-MM-dd HH:mm:ss', 'uuuu-MM-dd HH:mm', 'uuuu-MM-dd',
         'dd-MMM-uuuu HH:mm:ss.SSS', 'dd-MMM-uuuu HH:mm:ss', 'dd-MMM-uuuu HH:mm', 'dd-MMM-uuuu',
         'MM/dd/uuuu HH:mm:ss', 'MM/dd/uuuu HH:mm', 'MM/dd/uuuu', 'uuuu/MM/dd HH:mm:ss', 'uuuu/MM/dd HH:mm', 'uuuu/MM/dd',
         'dd.MM.uuuu HH:mm:ss', 'dd.MM.uuuu HH:mm', 'dd.MM.uuuu', 'dd MMM uuuu HH:mm:ss', 'dd MMM uuuu', 'MMM d, uuuu', 'MMMM d, uuuu',
         'd MMMM uuuu', 'MMMM uuuu', 'uuuuMMdd']


def _parse_auto(texts):
    """Wall seconds and a display format: the first standard format that reads every text."""
    if all((t or '').strip() == '' or (t or '').strip().lower() == 'nat' for t in texts):
        return np.full(len(texts), np.nan), FULL
    for f in _AUTO:
        r, ok = _parse(texts, f)
        if ok:
            return r, (FULL if any(c in 'Hhms' for c, _ in _tokens(f) if c != 'lit') else DATE)
    bad = next(t for t in texts if t and not np.isfinite(_parse([t], _AUTO[0])[0][0]))
    raise MError('MATLAB:datetime:UnrecognizedDateStringSuggestLocale', f"Could not recognize the date/time format of '{bad}'. Give it with 'InputFormat'.")


# ---- datetime ----------------------------------------------------------------------------------------------

class DateTime(VObj):
    cls = 'datetime'
    ARRAYS = ('a',)
    FILLS = {'a': np.nan}
    FUNCS = {}

    def __init__(self, a, fmt=FULL, tz=''):
        self.a = _2d(np.asarray(a, float))
        self.fmt = fmt
        self.tz = tz

    def wall(self):
        return _to_wall(self.a, self.tz)

    def elem_strings(self):
        return _format(self.wall(), self.fmt, self.tz)

    def coerce(self, v):
        if type(v) is DateTime:
            if bool(v.tz) != bool(self.tz):
                raise MError('MATLAB:datetime:IncompatibleTZ', 'Cannot combine or compare a datetime array with a time zone with one without.')
            return v if v.tz == self.tz or not self.tz else DateTime(v.a, self.fmt, self.tz)
        if type(v) in (Char, Str, Cell):
            texts = text_list(v) if type(v) is not Char or v.a.shape[0] <= 1 else v.row_strs()
            r, ok = _parse(texts, self.fmt)
            if not ok:
                r, _ = _parse_auto(texts)
            shp = (1, 1) if len(texts) == 1 else (shape_of(v) if type(v) is not Char else (len(texts), 1))
            return DateTime(_from_wall(r.reshape(shp, order='F'), self.tz), self.fmt, self.tz)
        if type(v) is np.ndarray and v.dtype.kind == 'f' and np.all(np.isnan(v)) or (type(v) is float and math.isnan(v)):
            return DateTime(np.full(shape_of(v), np.nan), self.fmt, self.tz)
        raise MError('MATLAB:datetime:InvalidComparison' if False else 'MATLAB:invalidConversion',
                     f'Unable to use a value of class {class_of(v)} as a datetime.')

    def key(self):
        return self.a

    def same_meta(self, other):
        return True

    # properties
    def propnames(self):
        return ['Format', 'TimeZone', 'Year', 'Month', 'Day', 'Hour', 'Minute', 'Second', 'SystemTimeZone']

    def getprop(self, name):
        parts = {'Year': 0, 'Month': 1, 'Day': 2, 'Hour': 3, 'Minute': 4, 'Second': 5}
        if name in parts:
            return out(_parts(self.wall())[parts[name]])
        if name == 'Format':
            return Char.of(self.fmt)
        if name == 'TimeZone':
            return Char.of(self.tz)
        if name == 'SystemTimeZone':
            return Char.of('UTC' if time.timezone == 0 else 'local')
        return super().getprop(name)

    def setprop(self, name, value):
        parts = {'Year': 0, 'Month': 1, 'Day': 2, 'Hour': 3, 'Minute': 4, 'Second': 5}
        if name in parts:
            p = list(_parts(self.wall()))
            p[parts[name]] = np.broadcast_to(np.asarray(darr(value), float), self.shape)
            self.a = _from_wall(_compose(*p), self.tz)
            return
        if name == 'Format':
            f = sval(value, 'Format', 'datetime')
            self.fmt = _check_format(f) if f not in ('default', 'defaultdate') else (FULL if f == 'default' else DATE)
            return
        if name == 'TimeZone':
            tz = sval(value, 'TimeZone', 'datetime')
            _valid_tz(tz)
            if not self.tz:
                self.a = _from_wall(self.a, tz)
            elif not tz:
                self.a = _to_wall(self.a, self.tz)
            self.tz = tz
            return
        super().setprop(name, value)

    # operators
    def binop(self, op, a, b):
        if op in ('==', '~=', '<', '<=', '>', '>='):
            o = a if type(a) is DateTime else b
            A, B = o.coerce(a), o.coerce(b)
            x, y = _bcast(A.a, B.a)
            with np.errstate(invalid='ignore'):
                r = {'==': x == y, '~=': x != y, '<': x < y, '<=': x <= y, '>': x > y, '>=': x >= y}[op]
            return _out_bool(r)
        if op == '+':
            if type(a) is not DateTime:
                a, b = b, a
            return a._plus(b, 1)
        if op == '-':
            if type(a) is DateTime and type(b) is DateTime:
                if bool(a.tz) != bool(b.tz):
                    raise MError('MATLAB:datetime:IncompatibleTZ', 'Cannot subtract a datetime with a time zone from one without.')
                x, y = _bcast(a.a, b.a)
                return Duration(x - y)
            if type(a) is DateTime:
                return a._plus(b, -1)
            if type(b) is DateTime and type(a) in (Char, Str):
                return b.coerce(a).binop('-', b.coerce(a), b)
        raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for operands of type 'datetime'" + (f" and '{class_of(b if a is self else a)}'." if True else '.'))

    def _plus(self, v, sign):
        if type(v) is Duration:
            x, y = _bcast(self.a, v.a)
            return DateTime(x + sign * y, self.fmt, self.tz)
        if type(v) is CalDuration:
            w = self.wall()
            w, mo, d, t = _bcast(w, v.mo, v.d, v.t)
            w2 = _add_months(w, sign * mo)
            w2 = w2 + sign * d * DAY
            res = _from_wall(w2, self.tz) + sign * t
            return DateTime(res, self.fmt, self.tz)
        if type(v) in (float, bool) or (type(v) is np.ndarray and v.dtype.kind in 'fib'):
            x, y = _bcast(self.a, np.asarray(v, float))
            return DateTime(x + sign * y * DAY, self.fmt, self.tz)
        raise MError('MATLAB:datetime:InvalidPlusMinus' if False else 'MATLAB:UndefinedFunction',
                     f"Addition and subtraction of a datetime take a duration, a calendarDuration or a number of days, not a {class_of(v)}.")

    def unop(self, op):
        if op in (".'", "'"):
            return self.transposed()
        if op == '+':
            return self
        raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for operands of type 'datetime'.")

    def colon(self, a, step, b):
        A = a if type(a) is DateTime else b.coerce(a)
        B = A.coerce(b)
        if numel(A) != 1 or numel(B) != 1:
            raise MError('MATLAB:colon:nonScalarInputs', 'The colon operator takes scalars.')
        start, stop = float(A.a.reshape(-1)[0]), float(B.a.reshape(-1)[0])
        if step is None:
            step = Duration(np.array([[DAY]]))
        if type(step) in (float, bool) or (type(step) is np.ndarray and numel(step) == 1):
            step = Duration(np.array([[float(num(step)) * DAY]]))
        if type(step) is Duration:
            h = float(step.a.reshape(-1)[0])
            if h == 0 or not math.isfinite(h) or (stop - start) / h < 0:
                return DateTime(np.zeros((1, 0)), A.fmt, A.tz)
            n = int(math.floor((stop - start) / h + 1e-10)) + 1
            return DateTime((start + h * np.arange(n)).reshape(1, -1), A.fmt, A.tz)
        if type(step) is CalDuration:
            vals = []
            k = 0
            mo, d, t = (float(x.reshape(-1)[0]) for x in (step.mo, step.d, step.t))
            if mo == 0 and d == 0 and t == 0:
                return DateTime(np.zeros((1, 0)), A.fmt, A.tz)
            ws = float(_to_wall(np.array(start), A.tz))
            while k < 1000000:
                w = _add_months(np.array([ws]), k * mo) + k * d * DAY
                x = float(_from_wall(w, A.tz)[0]) + k * t
                forward = (mo, d, t) > (0, 0, 0)
                if (forward and x > stop + 1e-6) or (not forward and x < stop - 1e-6):
                    break
                vals.append(x)
                k += 1
            return DateTime(np.array(vals).reshape(1, -1), A.fmt, A.tz)
        raise MError('MATLAB:colon:InvalidStep', 'The step of a range of datetimes is a duration, a calendarDuration or a number of days.')


def _out_bool(r):
    r = np.asarray(r, bool)
    if r.ndim < 2:
        r = r.reshape(1, -1) if r.ndim == 1 else r.reshape(1, 1)
    return bool(r.reshape(-1)[0]) if r.size == 1 and r.shape == (1, 1) else r


# ---- duration ----------------------------------------------------------------------------------------------

_DUR_UNITS = {'y': (365.2425 * DAY, 'yr', 'yrs'), 'd': (DAY, 'day', 'days'), 'h': (3600.0, 'hr', 'hr'),
              'm': (60.0, 'min', 'min'), 's': (1.0, 'sec', 'sec')}
_DUR_FORMATS = ('hh:mm:ss', 'dd:hh:mm:ss', 'hh:mm', 'mm:ss', 'y', 'd', 'h', 'm', 's')


def _short_g(x):
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return f'{x:.5g}'


def _dur_strings(a, fmt):
    a = np.asarray(a, float)
    res = np.empty(a.shape, object)
    base, _, frac = fmt.partition('.')
    nfrac = len(frac)
    for idx in np.ndindex(a.shape):
        x = a[idx]
        if np.isnan(x):
            res[idx] = 'NaN'
            continue
        if np.isinf(x):
            res[idx] = ('-' if x < 0 else '') + 'Inf'
            continue
        if base in _DUR_UNITS:
            u, one, many = _DUR_UNITS[base]
            v = x / u
            res[idx] = f'{_short_g(v)} {one if abs(v) == 1 else many}'
            continue
        sign = '-' if x < 0 else ''
        x = abs(x)
        if nfrac:
            x = math.floor(x * 10 ** nfrac + 1e-6) / 10 ** nfrac
        whole = math.floor(x + 1e-9)
        f = x - whole
        dd, rem = divmod(whole, 86400)
        hh, rem = divmod(rem, 3600)
        mm, ss = divmod(rem, 60)
        if base == 'dd:hh:mm:ss':
            s = f'{int(dd):02d}:{int(hh):02d}:{int(mm):02d}:{int(ss):02d}'
        elif base == 'hh:mm':
            s = f'{int(dd * 24 + hh):02d}:{int(mm):02d}'
        elif base == 'mm:ss':
            s = f'{int((dd * 24 + hh) * 60 + mm):02d}:{int(ss):02d}'
        else:
            s = f'{int(dd * 24 + hh):02d}:{int(mm):02d}:{int(ss):02d}'
        if nfrac:
            s += '.' + str(int(round(f * 10 ** nfrac))).rjust(nfrac, '0')[:nfrac]
        res[idx] = sign + s
    return res


class Duration(VObj):
    cls = 'duration'
    ARRAYS = ('a',)
    FILLS = {'a': np.nan}
    FUNCS = {}

    def __init__(self, a, fmt='hh:mm:ss'):
        self.a = _2d(np.asarray(a, float))
        self.fmt = fmt

    def elem_strings(self):
        return _dur_strings(self.a, self.fmt)

    def coerce(self, v):
        if type(v) is Duration:
            return v
        if type(v) in (Char, Str, Cell):
            texts = text_list(v)
            vals = np.array([_dur_from_text(t, self.fmt) for t in texts], float)
            return Duration(vals.reshape((1, 1) if len(texts) == 1 else shape_of(v), order='F'), self.fmt)
        if (type(v) is np.ndarray and v.dtype.kind == 'f' and np.all(np.isnan(v))) or (type(v) is float and math.isnan(v)):
            return Duration(np.full(shape_of(v), np.nan), self.fmt)
        raise MError('MATLAB:invalidConversion', f'Unable to use a value of class {class_of(v)} as a duration.')

    def propnames(self):
        return ['Format']

    def getprop(self, name):
        if name == 'Format':
            return Char.of(self.fmt)
        return super().getprop(name)

    def setprop(self, name, value):
        if name == 'Format':
            f = sval(value, 'Format', 'duration')
            if f.partition('.')[0] not in _DUR_FORMATS or (f.partition('.')[2] and set(f.partition('.')[2]) != {'S'}):
                raise MError('MATLAB:duration:UnrecognizedFormat', f"'{f}' is not a duration format: use 'hh:mm:ss', 'dd:hh:mm:ss', 'hh:mm', 'mm:ss' (each may end in .SSS), 'y', 'd', 'h', 'm' or 's'.")
            self.fmt = f
            return
        super().setprop(name, value)

    def binop(self, op, a, b):
        if type(a) is DateTime or type(b) is DateTime:
            return DateTime.binop(a if type(a) is DateTime else b, op, a, b)
        if type(a) is CalDuration or type(b) is CalDuration:
            return CalDuration.binop(a if type(a) is CalDuration else b, op, a, b)
        if op in ('==', '~=', '<', '<=', '>', '>='):
            o = a if type(a) is Duration else b
            A, B = o.coerce(a), o.coerce(b)
            x, y = _bcast(A.a, B.a)
            with np.errstate(invalid='ignore'):
                r = {'==': x == y, '~=': x != y, '<': x < y, '<=': x <= y, '>': x > y, '>=': x >= y}[op]
            return _out_bool(r)
        fmt = a.fmt if type(a) is Duration else b.fmt
        if op in ('+', '-'):
            if type(a) is not Duration or type(b) is not Duration:
                raise MError('MATLAB:duration:AdditionNotDefined', 'Durations are added to durations (or datetimes): give a number of hours, say, as hours(x).')
            x, y = _bcast(a.a, b.a)
            return Duration(x + y if op == '+' else x - y, fmt)
        if op in ('*', '.*'):
            if type(a) is Duration and type(b) is Duration:
                raise MError('MATLAB:duration:MultiplicationNotDefined', 'Durations cannot be multiplied by durations.')
            d, n = (a, b) if type(a) is Duration else (b, a)
            nv = np.asarray(darr(n), float)
            if op == '*' and numel(d) != 1 and nv.size != 1:
                return Duration(d.a @ nv if type(a) is Duration else nv @ d.a, fmt)
            x, y = _bcast(d.a, nv)
            return Duration(x * y, fmt)
        if op in ('/', './'):
            if type(a) is Duration and type(b) is Duration:
                x, y = _bcast(a.a, b.a)
                with np.errstate(divide='ignore', invalid='ignore'):
                    return out(x / y)
            if type(a) is Duration:
                x, y = _bcast(a.a, np.asarray(darr(b), float))
                with np.errstate(divide='ignore', invalid='ignore'):
                    return Duration(x / y, fmt)
        raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for operands of type 'duration'.")

    def unop(self, op):
        if op == '-':
            return Duration(-self.a, self.fmt)
        if op == '+':
            return self
        return super().unop(op)

    def colon(self, a, step, b):
        A = a if type(a) is Duration else b.coerce(a) if type(b) is Duration else step.coerce(a)
        B = A.coerce(b)
        start, stop = float(A.a.reshape(-1)[0]), float(B.a.reshape(-1)[0])
        if step is None:
            h = 1.0 if A.fmt == 's' else DAY if A.fmt == 'd' else 3600.0 if A.fmt == 'h' else 60.0 if A.fmt == 'm' else 1.0
        elif type(step) is Duration:
            h = float(step.a.reshape(-1)[0])
        else:
            raise MError('MATLAB:colon:InvalidStep', 'The step of a range of durations is a duration.')
        if h == 0 or (stop - start) / h < 0:
            return Duration(np.zeros((1, 0)), A.fmt)
        n = int(math.floor((stop - start) / h + 1e-10)) + 1
        return Duration((start + h * np.arange(n)).reshape(1, -1), A.fmt)


def _dur_from_text(t, fmt):
    t = (t or '').strip()
    if t == '' or t.lower() == 'nan':
        return np.nan
    m = re.match(r'^([+-]?)(?:(\d+):)?(\d+):(\d{1,2})(?::(\d{1,2}(?:\.\d*)?))?$', t)
    if m:
        sg = -1 if m.group(1) == '-' else 1
        a, b, c, d = m.group(2), m.group(3), m.group(4), m.group(5)
        if d is not None:                       # dd:hh:mm:ss or hh:mm:ss
            if a is not None:
                return sg * (int(a) * DAY + int(b) * 3600 + int(c) * 60 + float(d))
        if a is not None:
            return sg * (int(a) * 3600 + int(b) * 60 + float(c))
        if fmt == 'mm:ss':
            return sg * (int(b) * 60 + float(c))
        return sg * (int(b) * 3600 + int(c) * 60)
    m = re.match(r'^([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*(yrs?|years?|days?|d|hr|hours?|h|min|minutes?|m|sec|seconds?|s)$', t)
    if m:
        unit = m.group(2).lower()
        u = 365.2425 * DAY if unit.startswith('y') else DAY if unit.startswith('d') else 3600.0 if unit.startswith('h') else 60.0 if unit.startswith('m') else 1.0
        return float(m.group(1)) * u
    raise MError('MATLAB:duration:UnrecognizedFormat', f"Could not read '{t}' as a duration.")


# ---- calendarDuration ------------------------------------------------------------------------------------

class CalDuration(VObj):
    cls = 'calendarDuration'
    ARRAYS = ('mo', 'd', 't')
    FILLS = {'mo': np.nan, 'd': np.nan, 't': np.nan}
    FUNCS = {}

    def __init__(self, mo, d, t, fmt='ymdt'):
        mo, d, t = _bcast(np.asarray(mo, float), np.asarray(d, float), np.asarray(t, float))
        self.mo, self.d, self.t = _2d(mo.copy()), _2d(d.copy()), _2d(t.copy())
        self.fmt = fmt

    def elem_strings(self):
        res = np.empty(self.mo.shape, object)
        for idx in np.ndindex(self.mo.shape):
            mo, d, t = self.mo[idx], self.d[idx], self.t[idx]
            if np.isnan(mo) or np.isnan(d) or np.isnan(t):
                res[idx] = 'NaN'
                continue
            y = int(mo / 12)
            m = mo - 12 * y
            parts = []
            if y:
                parts.append(f'{y}y')
            if m:
                parts.append(f'{_short_g(m)}mo')
            if d:
                parts.append(f'{_short_g(d)}d')
            if t:
                sg = '-' if t < 0 else ''
                tt = abs(t)
                h, rem = divmod(tt, 3600)
                mi, s = divmod(rem, 60)
                tp = []
                if h:
                    tp.append(f'{sg}{int(h)}h')
                if mi:
                    tp.append(f'{sg}{int(mi)}m')
                if s:
                    tp.append(f'{sg}{_short_g(round(s, 4))}s')
                parts += tp
            res[idx] = ' '.join(parts) if parts else '0d'
        return res

    def coerce(self, v):
        if type(v) is CalDuration:
            return v
        if type(v) is Duration:
            return CalDuration(np.zeros(v.shape), np.zeros(v.shape), v.a)
        if (type(v) is np.ndarray and v.dtype.kind == 'f' and np.all(np.isnan(v))) or (type(v) is float and math.isnan(v)):
            z = np.full(shape_of(v), np.nan)
            return CalDuration(z, z, z)
        raise MError('MATLAB:invalidConversion', f'Unable to use a value of class {class_of(v)} as a calendarDuration.')

    def key(self):
        # equal when every part is: a key that only equality reads
        return self.mo * 1e12 + self.d * 1e6 + self.t

    def propnames(self):
        return ['Format']

    def getprop(self, name):
        if name == 'Format':
            return Char.of(self.fmt)
        return super().getprop(name)

    def setprop(self, name, value):
        if name == 'Format':
            self.fmt = sval(value, 'Format', 'calendarDuration')
            return
        super().setprop(name, value)

    def binop(self, op, a, b):
        if type(a) is DateTime or type(b) is DateTime:
            return DateTime.binop(a if type(a) is DateTime else b, op, a, b)
        if op in ('==', '~='):
            A, B = self.coerce(a), self.coerce(b)
            e = (A.mo == B.mo) & (A.d == B.d) & (A.t == B.t)
            return _out_bool(e if op == '==' else ~e)
        if op in ('+', '-'):
            A, B = self.coerce(a), self.coerce(b)
            s = 1 if op == '+' else -1
            return CalDuration(A.mo + s * B.mo, A.d + s * B.d, A.t + s * B.t, self.fmt)
        if op in ('*', '.*'):
            c, n = (a, b) if type(a) is CalDuration else (b, a)
            if type(n) is CalDuration:
                raise MError('MATLAB:calendarDuration:MultiplicationNotDefined', 'calendarDurations cannot be multiplied together.')
            nv = np.asarray(darr(n), float)
            if np.any(nv != np.round(nv)):
                raise MError('MATLAB:calendarDuration:NonIntegerMultiplier', 'A calendarDuration can only be multiplied by whole numbers.')
            return CalDuration(c.mo * nv, c.d * nv, c.t * nv, c.fmt)
        raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for operands of type 'calendarDuration'.")

    def unop(self, op):
        if op == '-':
            return CalDuration(-self.mo, -self.d, -self.t, self.fmt)
        if op == '+':
            return self
        return super().unop(op)


# ---- making them -------------------------------------------------------------------------------------------

def _name_values(args, names, fn):
    """Split trailing name-value pairs (names lower case) from the data inputs."""
    data = list(args)
    opts = {}
    while len(data) >= 2 and opt_str(data[-2]) is not None and opt_str(data[-2]).lower() in names:
        opts[opt_str(data[-2]).lower()] = data[-1]
        data = data[:-2]
    return data, opts


def _nums(a):
    return np.asarray(darr(a), float)


@bi('datetime', nout=1, arr=False)
def datetime(nargout, *args):
    """datetime('now'), datetime(y, mo, d), datetime(y, mo, d, h, mi, s[, ms]),
    datetime(DateVectors), datetime(text), datetime(text, 'InputFormat', f),
    datetime(X, 'ConvertFrom', kind): points in time; 'Format' and
    'TimeZone' as options."""
    data, opts = _name_values(args, ('format', 'inputformat', 'convertfrom', 'timezone', 'locale', 'pivotyear', 'epoch', 'ticksperseconds', 'tickspersecond'), 'datetime')
    tz = _valid_tz(sval(opts['timezone'], 'TimeZone', 'datetime')) if 'timezone' in opts else ''
    fmt = sval(opts['format'], 'Format', 'datetime') if 'format' in opts else None
    if fmt is not None and fmt not in ('default', 'defaultdate', 'preserveinput'):
        _check_format(fmt)
    if fmt == 'default':
        fmt = FULL
    if fmt == 'defaultdate':
        fmt = DATE

    def make(wall, default_fmt):
        f = fmt if fmt not in (None, 'preserveinput') else default_fmt
        return DateTime(_from_wall(wall, tz), f, tz)
    if not data:
        data = [Char.of('now')]
    if len(data) == 1 and (type(data[0]) in (Char, Str, Cell)):
        texts = text_list(data[0]) if type(data[0]) is not Char or data[0].a.shape[0] <= 1 else data[0].row_strs()
        words = {'now': None, 'today': 0, 'tomorrow': 1, 'yesterday': -1}
        if len(texts) == 1 and texts[0].strip().lower() in words:
            w = texts[0].strip().lower()
            if tz:
                nowa = time.time()
                wall = float(_to_wall(np.array(nowa), tz))
            else:
                n = _dt.datetime.now()
                wall = float(_compose(n.year, n.month, n.day, n.hour, n.minute, n.second + n.microsecond / 1e6))
            if words[w] is None:
                return make(np.array([[wall]]), FULL)
            day = math.floor(wall / DAY) + words[w]
            return make(np.array([[day * DAY]]), DATE)
        if 'inputformat' in opts:
            f = sval(opts['inputformat'], 'InputFormat', 'datetime')
            r, ok = _parse(texts, f)
            if not ok:
                bad = next(t for t, x in zip(texts, r) if not np.isfinite(x) and (t or '').strip() not in ('', 'NaT'))
                raise err('MATLAB:datetime:ParseErr', f"Unable to read '{bad}' with the format '{f}'.", 'datetime')
            # displayed in the default format (with the time if the input has one) unless 'Format' says otherwise
            if fmt is None:
                show = FULL if any(c in 'Hhms' for c, _ in _tokens(f) if c != 'lit') else DATE
            else:
                show = f if fmt == 'preserveinput' else fmt
            shp = (1, 1) if len(texts) == 1 else (shape_of(data[0]) if type(data[0]) is not Char else (len(texts), 1))
            return DateTime(_from_wall(r.reshape(shp, order='F'), tz), show, tz)
        r, f = _parse_auto(texts)
        shp = (1, 1) if len(texts) == 1 else (shape_of(data[0]) if type(data[0]) is not Char else (len(texts), 1))
        return make(r.reshape(shp, order='F'), f)
    if len(data) == 1 and type(data[0]) is DateTime:
        d = data[0]
        r = DateTime(d.a, fmt or d.fmt, d.tz)
        if 'timezone' in opts:
            r.setprop('TimeZone', Char.of(tz))
        return r
    if 'convertfrom' in opts:
        kind = sval(opts['convertfrom'], 'ConvertFrom', 'datetime').lower()
        X = _nums(data[0])
        if kind == 'datenum':
            wall = (X - _EPOCH) * DAY
        elif kind in ('posixtime', 'epochtime'):
            if kind == 'epochtime':
                tps = float(num(opts.get('tickspersecond', 1.0)))
                ep = opts.get('epoch')
                e0 = 0.0 if ep is None else float((ep if type(ep) is DateTime else datetime(1, ep)).a.reshape(-1)[0])
                secs = e0 + X / tps
            else:
                secs = X
            return DateTime(secs if tz else secs, fmt or FULL, tz) if tz else DateTime(secs, fmt or FULL, '')
        elif kind == 'excel':
            wall = (X + 693960 - _EPOCH) * DAY
        elif kind == 'excel1904':
            wall = (X + 695422 - _EPOCH) * DAY
        elif kind == 'juliandate':
            secs = (X - 2440587.5) * DAY
            return DateTime(secs, fmt or FULL, tz)
        elif kind == 'modifiedjuliandate':
            secs = (X - 40587.0) * DAY
            return DateTime(secs, fmt or FULL, tz)
        elif kind == 'yyyymmdd':
            yy = np.floor(X / 10000)
            mm = np.floor((X - yy * 10000) / 100)
            dd = X - yy * 10000 - mm * 100
            wall = _compose(yy, mm, dd)
            return make(wall, DATE)
        elif kind == 'datevec':
            return datetime(1, out(X), *(a for k, v in opts.items() if k in ('format', 'timezone') for a in (Char.of(k), v)))
        else:
            raise err('MATLAB:datetime:InvalidConvertFrom', f"'{kind}' is not a ConvertFrom kind: use 'datenum', 'posixtime', 'excel', 'excel1904', 'juliandate', 'modifiedjuliandate', 'yyyymmdd' or 'epochtime'.", 'datetime')
        return make(wall, FULL)
    if len(data) == 1:
        X = _nums(data[0])
        if X.ndim == 2 and X.shape[1] in (3, 6):
            cols = [X[:, k] for k in range(X.shape[1])] + [np.zeros(X.shape[0])] * (6 - X.shape[1])
            return make(_compose(*cols).reshape(-1, 1), DATE if X.shape[1] == 3 else FULL)
        raise err('MATLAB:datetime:InvalidNumericData', "Give date vectors (rows of [y mo d] or [y mo d h mi s]), or the kind of numbers with 'ConvertFrom'.", 'datetime')
    if len(data) in (3, 6, 7):
        vals = [_nums(a) for a in data]
        if len(data) == 7:
            vals = vals[:5] + [vals[5] + vals[6] / 1000]
        w = _compose(*vals)
        return make(_2d(w), DATE if len(data) == 3 else FULL)
    raise err('MATLAB:datetime:InvalidInput', 'datetime takes text, date vectors, (y, mo, d), (y, mo, d, h, mi, s) or numbers with ConvertFrom.', 'datetime')


@bi('NaT', arr=False)
def nat(nargout, *args):
    """NaT, NaT(n), NaT(m, n): Not-a-Time datetimes."""
    data, opts = _name_values(args, ('format', 'timezone'), 'NaT')
    shape = (1, 1) if not data else ((ival(data[0]), ival(data[0])) if len(data) == 1 and numel(data[0]) == 1 else tuple(int(x) for x in _nums(data[0]).reshape(-1)) if len(data) == 1 else tuple(ival(a) for a in data))
    tz = sval(opts['timezone'], 'TimeZone', 'NaT') if 'timezone' in opts else ''
    return DateTime(np.full(shape, np.nan), sval(opts['format'], 'Format', 'NaT') if 'format' in opts else FULL, tz)


def _need(v, cls, fn):
    if type(v) is not cls:
        raise err(f'MATLAB:{fn}:InvalidInput', f'The input must be a {cls.cls}.', fn)
    return v


@bi('isdatetime', arr=False)
def isdatetime(nargout, *args):
    nargchk(args, 1, 1, 'isdatetime')
    return type(args[0]) is DateTime


@bi('isnat', arr=False)
def isnat(nargout, *args):
    nargchk(args, 1, 1, 'isnat')
    return _out_bool(np.isnan(_need(args[0], DateTime, 'isnat').a))


@bi('isduration', arr=False)
def isduration(nargout, *args):
    nargchk(args, 1, 1, 'isduration')
    return type(args[0]) is Duration


@bi('iscalendarduration', arr=False)
def iscalendarduration(nargout, *args):
    nargchk(args, 1, 1, 'iscalendarduration')
    return type(args[0]) is CalDuration


def _field(k, fn):
    def f(nargout, *args):
        nargchk(args, 1, 2, fn)
        t = _need(args[0], DateTime, fn)
        p = _parts(t.wall())
        if fn == 'month' and len(args) > 1:
            kind = sval(args[1], 'kind', fn).lower()
            if kind in ('name', 'shortname'):
                return Cell.of_list([Char.of('' if not np.isfinite(m) else (_MONTHS[int(m) - 1] if kind == 'name' else _MONTHS[int(m) - 1][:3])) for m in p[1].reshape(-1, order='F')], t.shape)
            if kind != 'monthofyear':
                raise err('MATLAB:month:InvalidKind', "The kind is 'monthofyear', 'name' or 'shortname'.", fn)
        if fn == 'day' and len(args) > 1:
            kind = sval(args[1], 'kind', fn).lower()
            days = np.floor(t.wall() / DAY)
            if kind == 'dayofweek':
                return out(np.where(np.isfinite(days), (days + 4) % 7 + 1, np.nan))
            if kind == 'dayofyear':
                return out(days - _days_from_civil(np.where(np.isfinite(p[0]), p[0], 1970).astype(np.int64), 1, 1) + 1)
            if kind in ('name', 'shortname'):
                return Cell.of_list([Char.of('' if not np.isfinite(x) else (_DAYS[int((x + 4) % 7)] if kind == 'name' else _DAYS[int((x + 4) % 7)][:3])) for x in days.reshape(-1, order='F')], t.shape)
            if kind != 'dayofmonth':
                raise err('MATLAB:day:InvalidKind', "The kind is 'dayofmonth', 'dayofweek', 'dayofyear', 'name' or 'shortname'.", fn)
        return out(p[k])
    return f


bi('year', arr=False)(_field(0, 'year'))
bi('month', arr=False)(_field(1, 'month'))
bi('hour', arr=False)(_field(3, 'hour'))
bi('minute', arr=False)(_field(4, 'minute'))
bi('second', arr=False)(_field(5, 'second'))


@bi('day', arr=False)
def day(nargout, *args):
    """day(t): the day of the month; day(t, kind): 'dayofweek' (Sunday 1),
    'dayofyear', 'name' or 'shortname'."""
    return _field(2, 'day')(nargout, *args)


@bi('quarter', arr=False)
def quarter(nargout, *args):
    nargchk(args, 1, 1, 'quarter')
    m = _parts(_need(args[0], DateTime, 'quarter').wall())[1]
    return out(np.floor((m - 1) / 3) + 1)


@bi('week', arr=False)
def week(nargout, *args):
    """week(t): the week of the year (the week of 1 January is 1, weeks
    starting on Sunday); week(t, 'weekofmonth')."""
    nargchk(args, 1, 2, 'week')
    t = _need(args[0], DateTime, 'week')
    kind = sval(args[1], 'kind', 'week').lower() if len(args) > 1 else 'weekofyear'
    w = t.wall()
    days = np.floor(np.where(np.isfinite(w), w, 0) / DAY)
    y, mo, d = (x for x in _parts(w)[:3])
    first = _days_from_civil(np.where(np.isfinite(y), y, 1970).astype(np.int64), 1 if kind == 'weekofyear' else np.where(np.isfinite(mo), mo, 1).astype(np.int64), 1)
    wd_first = (first + 4) % 7                   # 0 Sunday
    r = np.floor((days - first + wd_first) / 7) + 1
    return out(np.where(np.isfinite(w), r, np.nan))


@bi('ymd', nout=3, arr=False)
def ymd(nargout, *args):
    nargchk(args, 1, 1, 'ymd')
    y, m, d = _parts(_need(args[0], DateTime, 'ymd').wall())[:3]
    return (out(y), out(m), out(d))[:max(nargout, 1)] if nargout > 1 else out(y)


@bi('hms', nout=3, arr=False)
def hms(nargout, *args):
    """[h, m, s] = hms(t) of datetimes or of durations."""
    nargchk(args, 1, 1, 'hms')
    v = args[0]
    if type(v) is Duration:
        a = v.a
        sg = np.sign(a)
        x = np.abs(a)
        h = np.floor(x / 3600)
        m = np.floor((x - h * 3600) / 60)
        s = x - h * 3600 - m * 60
        res = (out(sg * h), out(sg * m), out(sg * s))
    else:
        h, m, s = _parts(_need(v, DateTime, 'hms').wall())[3:]
        res = (out(h), out(m), out(s))
    return res[:max(nargout, 1)] if nargout > 1 else res[0]


@bi('timeofday', arr=False)
def timeofday(nargout, *args):
    nargchk(args, 1, 1, 'timeofday')
    w = _need(args[0], DateTime, 'timeofday').wall()
    return Duration(w - np.floor(w / DAY) * DAY)


@bi('isweekend', arr=False)
def isweekend(nargout, *args):
    nargchk(args, 1, 1, 'isweekend')
    w = _need(args[0], DateTime, 'isweekend').wall()
    wd = (np.floor(np.where(np.isfinite(w), w, 0) / DAY) + 4) % 7
    return _out_bool(np.isfinite(w) & ((wd == 0) | (wd == 6)))


@bi('isbetween', arr=False)
def isbetween(nargout, *args):
    """isbetween(t, lower, upper): lower <= t <= upper (or 'open', 'openleft', 'openright' as a fourth input)."""
    nargchk(args, 3, 4, 'isbetween')
    t = args[0] if type(args[0]) is DateTime else None
    if t is None:
        raise err('MATLAB:isbetween:InvalidInput', 'The first input must be a datetime.', 'isbetween')
    lo, hi = t.coerce(args[1]), t.coerce(args[2])
    kind = sval(args[3], 'interval', 'isbetween').lower() if len(args) > 3 else 'closed'
    x, a, b = _bcast(t.a, lo.a, hi.a)
    left = x > a if kind in ('open', 'openleft') else x >= a
    right = x < b if kind in ('open', 'openright') else x <= b
    return _out_bool(left & right)


@bi('posixtime', arr=False)
def posixtime(nargout, *args):
    nargchk(args, 1, 1, 'posixtime')
    t = _need(args[0], DateTime, 'posixtime')
    return out(t.a.copy())


@bi('juliandate', arr=False)
def juliandate(nargout, *args):
    nargchk(args, 1, 2, 'juliandate')
    t = _need(args[0], DateTime, 'juliandate')
    jd = t.a / DAY + 2440587.5
    if len(args) > 1 and sval(args[1], 'kind', 'juliandate').lower() == 'modifiedjuliandate':
        jd = jd - 2400000.5
    return out(jd)


@bi('exceltime', arr=False)
def exceltime(nargout, *args):
    nargchk(args, 1, 2, 'exceltime')
    t = _need(args[0], DateTime, 'exceltime')
    base = 693960 if len(args) < 2 or float(num(args[1])) == 1900 else 695422
    return out(t.wall() / DAY + _EPOCH - base)


@bi('convertTo', arr=False)
def convertTo(nargout, *args):
    """convertTo(t, kind): 'datenum', 'posixtime', 'excel', 'excel1904', 'juliandate', 'modifiedjuliandate', 'yyyymmdd' or 'epochtime'."""
    nargchk(args, 2, 6, 'convertTo')
    t = _need(args[0], DateTime, 'convertTo')
    kind = sval(args[1], 'kind', 'convertTo').lower()
    if kind == 'datenum':
        return out(t.wall() / DAY + _EPOCH)
    if kind == 'posixtime':
        return out(t.a.copy())
    if kind in ('excel', 'excel1904'):
        return exceltime(1, t, 1900.0 if kind == 'excel' else 1904.0)
    if kind in ('juliandate', 'modifiedjuliandate'):
        return juliandate(1, t, Char.of(kind))
    if kind == 'yyyymmdd':
        y, m, d = _parts(t.wall())[:3]
        return out(y * 10000 + m * 100 + d)
    if kind == 'epochtime':
        _, opts = _name_values(args[2:], ('epoch', 'tickspersecond'), 'convertTo')
        ep = opts.get('epoch')
        e0 = 0.0 if ep is None else float((ep if type(ep) is DateTime else datetime(1, ep)).a.reshape(-1)[0])
        tps = float(num(opts.get('tickspersecond', 1.0)))
        return out((t.a - e0) * tps)
    raise err('MATLAB:convertTo:InvalidKind', f"'{kind}' is not a kind convertTo knows.", 'convertTo')


@bi('tzoffset', nout=2, arr=False)
def tzoffset(nargout, *args):
    nargchk(args, 1, 1, 'tzoffset')
    t = _need(args[0], DateTime, 'tzoffset')
    z = _zone(t.tz)
    off = np.zeros(t.shape) if z is None else z(t.a)
    r = Duration(np.where(np.isfinite(t.a), off, np.nan))
    return (r, Duration(np.zeros(t.shape))) if nargout > 1 else r


_UNITS = {'year': 'years', 'years': 'years', 'quarter': 'quarters', 'quarters': 'quarters', 'month': 'months', 'months': 'months',
          'week': 'weeks', 'weeks': 'weeks', 'day': 'days', 'days': 'days', 'hour': 'hours', 'hours': 'hours',
          'minute': 'minutes', 'minutes': 'minutes', 'second': 'seconds', 'seconds': 'seconds'}


def _start_of(w, unit):
    y, mo, d, h, mi, s = _parts(w)
    if unit == 'years':
        return _compose(y, 1, 1)
    if unit == 'quarters':
        return _compose(y, np.floor((mo - 1) / 3) * 3 + 1, 1)
    if unit == 'months':
        return _compose(y, mo, 1)
    days = np.floor(w / DAY)
    if unit == 'weeks':
        return (days - (days + 4) % 7) * DAY
    if unit == 'days':
        return days * DAY
    if unit == 'hours':
        return days * DAY + h * 3600
    if unit == 'minutes':
        return days * DAY + h * 3600 + mi * 60
    return days * DAY + h * 3600 + mi * 60 + np.floor(s)


def _next_unit(w, unit, k=1):
    if unit in ('years', 'quarters', 'months'):
        return _add_months(w, k * {'years': 12, 'quarters': 3, 'months': 1}[unit])
    return w + k * {'weeks': 7 * DAY, 'days': DAY, 'hours': 3600, 'minutes': 60, 'seconds': 1}[unit]


@bi('dateshift', arr=False)
def dateshift(nargout, *args):
    """dateshift(t, 'start' or 'end', unit[, rule]): the start or the end of
    the unit (year, quarter, month, week, day, hour, minute, second) that
    holds t, or of the unit 'next', 'previous', 'current' or a number of
    units away; dateshift(t, 'dayofweek', day[, rule])."""
    nargchk(args, 3, 4, 'dateshift')
    t = _need(args[0], DateTime, 'dateshift')
    which = sval(args[1], 'which', 'dateshift').lower()
    w = t.wall()
    rule = args[3] if len(args) > 3 else Char.of('current')
    r = opt_str(rule)
    k = 0 if r is None and False else (0 if (r or '').lower() == 'current' else 1 if (r or '').lower() == 'next' else -1 if (r or '').lower() == 'previous' else None)
    kv = np.asarray(darr(rule), float) if k is None else np.full(t.shape, float(k))
    if which in ('start', 'end'):
        unit = _UNITS.get(sval(args[2], 'unit', 'dateshift').lower())
        if unit is None:
            raise err('MATLAB:dateshift:InvalidUnit', 'The unit is year, quarter, month, week, day, hour, minute or second.', 'dateshift')
        base = _start_of(w, unit)
        res = np.empty(base.shape)
        for idx in np.ndindex(base.shape):
            kk = float(np.broadcast_to(kv, base.shape)[idx])
            b = _next_unit(np.array([base[idx]]), unit, int(kk))[0]
            res[idx] = _next_unit(np.array([b]), unit, 1)[0] if which == 'end' else b
        res = np.where(np.isfinite(w), res, np.nan)
        return DateTime(_from_wall(res, t.tz), t.fmt, t.tz)
    if which == 'dayofweek':
        target = args[2]
        if opt_str(target) is not None:
            name = opt_str(target).lower()
            target = next((i + 1 for i, d in enumerate(_DAYS) if d.lower().startswith(name[:3])), None)
            if target is None:
                raise err('MATLAB:dateshift:InvalidDay', 'The day is a name or a number from 1 (Sunday) to 7.', 'dateshift')
        else:
            target = int(num(target))
        days = np.floor(w / DAY)
        wd = (days + 4) % 7 + 1
        rr = (r or 'next').lower() if r is not None else 'next'
        delta = (target - wd) % 7
        if rr == 'next':
            delta = np.where(delta == 0, 7, delta)
        elif rr == 'previous':
            delta = -((wd - target) % 7)
            delta = np.where(delta == 0, -7, delta)
        elif rr == 'nearest':
            delta = np.where(delta > 3, delta - 7, delta)
        res = (days + delta) * DAY + (w - days * DAY)
        return DateTime(_from_wall(res, t.tz), t.fmt, t.tz)
    raise err('MATLAB:dateshift:InvalidWhich', "The second input is 'start', 'end' or 'dayofweek'.", 'dateshift')


def _cal_between(w1, w2, comps):
    """The calendar components from w1 to w2 (whole months, then days, then time)."""
    mo = np.zeros(w1.shape)
    d = np.zeros(w1.shape)
    t = np.zeros(w1.shape)
    for idx in np.ndindex(w1.shape):
        a, b = float(w1[idx]), float(w2[idx])
        if not (np.isfinite(a) and np.isfinite(b)):
            mo[idx] = d[idx] = t[idx] = np.nan
            continue
        sign = 1
        if b < a:
            a, b, sign = b, a, -1
        months = 0
        if any(c in comps for c in ('years', 'quarters', 'months')):
            ya, ma = (int(x) for x in _parts(np.array([a]))[:2])
            yb, mb = (int(x) for x in _parts(np.array([b]))[:2])
            months = (yb - ya) * 12 + (mb - ma)
            while months > 0 and _add_months(np.array([a]), months)[0] > b:
                months -= 1
            if 'months' not in comps:
                step = 3 if 'quarters' in comps else 12
                months = months // step * step
        cur = _add_months(np.array([a]), months)[0] if months else a
        days = 0
        if any(c in comps for c in ('weeks', 'days')):
            days = int(math.floor((b - cur) / DAY + 1e-9))
            if 'days' not in comps:
                days = days // 7 * 7
            cur += days * DAY
        rest = b - cur if 'time' in comps else 0.0
        mo[idx], d[idx], t[idx] = sign * months, sign * days, sign * rest
    return mo, d, t


@bi('between', arr=False)
def between(nargout, *args):
    """between(t1, t2): the calendar difference from t1 to t2 (years,
    months, days and time); between(t1, t2, components), components from
    'years', 'quarters', 'months', 'weeks', 'days', 'time'."""
    nargchk(args, 2, 3, 'between')
    t1 = args[0] if type(args[0]) is DateTime else None
    if t1 is None:
        raise err('MATLAB:between:InvalidInput', 'The inputs must be datetimes.', 'between')
    t2 = t1.coerce(args[1])
    comps = ['years', 'months', 'days', 'time']
    if len(args) > 2:
        c = args[2]
        comps = [x.lower() for x in (text_list(c) if type(c) in (Cell, Str) else [sval(c, 'components', 'between')])]
        comps = ['days' if x in ('day',) else 'months' if x in ('month',) else 'years' if x in ('year',) else 'weeks' if x in ('week',) else 'quarters' if x in ('quarter',) else x for x in comps]
        if any(x not in ('years', 'quarters', 'months', 'weeks', 'days', 'time') for x in comps):
            raise err('MATLAB:between:InvalidComponent', "The components are 'years', 'quarters', 'months', 'weeks', 'days' and 'time'.", 'between')
    w1, w2 = _bcast(t1.wall(), t2.wall())
    mo, d, t = _cal_between(w1, w2, comps)
    return CalDuration(mo, d, t)


@bi('caldiff', arr=False)
def caldiff(nargout, *args):
    """caldiff(t): the calendar differences between consecutive datetimes (between(t(1:end-1), t(2:end)))."""
    nargchk(args, 1, 3, 'caldiff')
    t = _need(args[0], DateTime, 'caldiff')
    w = t.wall()
    col = w.shape[0] != 1
    v = w.reshape(-1, order='F')
    r = between(1, DateTime(_from_wall(v[:-1], t.tz), t.fmt, t.tz), DateTime(_from_wall(v[1:], t.tz), t.fmt, t.tz), *args[1:2])
    return r.mapped(lambda a: a.reshape((-1, 1) if col else (1, -1)))


# ---- durations from numbers, and numbers from durations ---------------------------------------------------

def _unit_fn(name, secs, fmt):
    def f(nargout, *args):
        nargchk(args, 1, 1, name)
        v = args[0]
        if type(v) is Duration:
            return out(v.a / secs)
        if type(v) in (DateTime, CalDuration) or type(v) in (Char, Str, Cell):
            raise err(f'MATLAB:{name}:InvalidInput', f'{name} takes numbers (to make durations) or durations (to give numbers).', name)
        return Duration(np.asarray(darr(v), float) * secs, fmt)
    f.__doc__ = f'{name}(x): x {name} as a duration; {name}(d): the duration d in {name}.'
    return f


for _n, _s, _f in (('years', 365.2425 * DAY, 'y'), ('days', DAY, 'd'), ('hours', 3600.0, 'h'), ('minutes', 60.0, 'm'),
                   ('seconds', 1.0, 's'), ('milliseconds', 1e-3, 's')):
    bi(_n, arr=False)(_unit_fn(_n, _s, _f))


@bi('duration', arr=False)
def duration(nargout, *args):
    """duration(h, m, s), duration(h, m, s, ms), duration([h m s]),
    duration(text), duration(text, 'InputFormat', f): lengths of time;
    'Format' as an option."""
    data, opts = _name_values(args, ('format', 'inputformat'), 'duration')
    fmt = sval(opts['format'], 'Format', 'duration') if 'format' in opts else 'hh:mm:ss'
    if not data:
        return Duration(np.zeros((1, 1)), fmt)
    if len(data) == 1 and type(data[0]) in (Char, Str, Cell):
        texts = text_list(data[0])
        f = sval(opts['inputformat'], 'InputFormat', 'duration') if 'inputformat' in opts else fmt
        vals = np.array([_dur_from_text(t, f) for t in texts], float)
        return Duration(vals.reshape((1, 1) if len(texts) == 1 else shape_of(data[0]), order='F'), fmt)
    if len(data) == 1:
        X = _nums(data[0])
        if X.ndim == 2 and X.shape[1] == 3:
            return Duration((X[:, 0] * 3600 + X[:, 1] * 60 + X[:, 2]).reshape(-1, 1), fmt)
        raise err('MATLAB:duration:InvalidNumericData', 'Give [h m s] rows, or h, m and s.', 'duration')
    if len(data) in (3, 4):
        h, m, s = (_nums(a) for a in data[:3])
        ms = _nums(data[3]) if len(data) > 3 else 0.0
        h, m, s, ms = _bcast(h, m, s, np.asarray(ms, float))
        return Duration(h * 3600 + m * 60 + s + ms / 1000, fmt)
    raise err('MATLAB:duration:InvalidInput', 'duration takes (h, m, s), (h, m, s, ms), [h m s] rows or text.', 'duration')


def _cal_fn(name, months, days):
    def f(nargout, *args):
        nargchk(args, 1, 1, name)
        v = args[0]
        if type(v) is CalDuration:
            if months:
                return out(np.fix(v.mo / months))
            return out(v.d / days)
        x = np.asarray(darr(v), float)
        if np.any(x != np.round(x)):
            raise err(f'MATLAB:{name}:NonInteger', f'{name} takes whole numbers.', name)
        z = np.zeros(x.shape)
        return CalDuration(x * months if months else z, x * days if days else z, z)
    f.__doc__ = f'{name}(n): n calendar {name[3:]} as a calendarDuration.'
    return f


for _n, _m, _d in (('calyears', 12, 0), ('calquarters', 3, 0), ('calmonths', 1, 0), ('calweeks', 0, 7), ('caldays', 0, 1)):
    bi(_n, arr=False)(_cal_fn(_n, _m, _d))


@bi('calendarDuration', arr=False)
def calendarDuration(nargout, *args):
    """calendarDuration(y, mo, d), calendarDuration(y, mo, d, h, mi, s),
    calendarDuration(y, mo, d, t) with t a duration, or rows [y mo d (h mi s)]."""
    data, opts = _name_values(args, ('format',), 'calendarDuration')
    fmt = sval(opts['format'], 'Format', 'calendarDuration') if 'format' in opts else 'ymdt'
    if len(data) == 1:
        X = _nums(data[0])
        if X.ndim != 2 or X.shape[1] not in (3, 6):
            raise err('MATLAB:calendarDuration:InvalidInput', 'Give rows of [y mo d] or [y mo d h mi s].', 'calendarDuration')
        data = [out(X[:, k].reshape(-1, 1)) for k in range(X.shape[1])]
    if len(data) == 3:
        y, mo, d = (_nums(a) for a in data)
        return CalDuration(y * 12 + mo, d, np.zeros(np.broadcast(y, mo, d).shape), fmt)
    if len(data) == 4 and type(data[3]) is Duration:
        y, mo, d = (_nums(a) for a in data[:3])
        return CalDuration(y * 12 + mo, d, data[3].a, fmt)
    if len(data) == 6:
        y, mo, d, h, mi, s = (_nums(a) for a in data)
        return CalDuration(y * 12 + mo, d, h * 3600 + mi * 60 + s, fmt)
    raise err('MATLAB:calendarDuration:InvalidInput', 'calendarDuration takes (y, mo, d), (y, mo, d, t), (y, mo, d, h, mi, s) or rows of them.', 'calendarDuration')


# ---- the existing functions on these values (vobj.wrap_builtins puts them in front) ----------------------

def _text_of(v):
    return np.asarray(v.elem_strings(), object)


def _char_fn(nargout, args):
    v = args[0]
    if len(args) > 1 and type(v) is DateTime:
        v = DateTime(v.a, _check_format(sval(args[1], 'format', 'char')), v.tz)
    return Char.rows([str(x) for x in _text_of(v).reshape(-1, order='F')])


def _string_fn(nargout, args):
    v = args[0]
    if len(args) > 1 and type(v) is DateTime:
        v = DateTime(v.a, _check_format(sval(args[1], 'format', 'string')), v.tz)
    s = _text_of(v)
    vals = [None if x in ('NaT',) and type(v) is DateTime else str(x) for x in s.reshape(-1, order='F')]
    return Str.from_list(vals, v.shape)


def _cellstr_fn(nargout, args):
    v = args[0]
    if len(args) > 1 and type(v) is DateTime:
        v = DateTime(v.a, _check_format(sval(args[1], 'format', 'cellstr')), v.tz)
    s = _text_of(v)
    return Cell.of_list([Char.of('' if x == 'NaT' else str(x)) for x in s.reshape(-1, order='F')], v.shape)


for _cls in (DateTime, Duration, CalDuration):
    _cls.FUNCS = dict(_cls.FUNCS)
    _cls.FUNCS['char'] = _char_fn
    _cls.FUNCS['string'] = _string_fn
    _cls.FUNCS['cellstr'] = _cellstr_fn


def _dt_datenum(nargout, args):
    t = args[0]
    if type(t) is not DateTime:
        return NotImplemented
    return out(t.wall() / DAY + _EPOCH)


def _dt_datevec(nargout, args):
    t = args[0]
    if type(t) is not DateTime:
        return NotImplemented
    p = _parts(t.wall())
    m = np.column_stack([x.reshape(-1, order='F') for x in p])
    if nargout <= 1:
        return out(m)
    return tuple(out(x.reshape(-1, 1)) for x in p)[:nargout]


def _dt_datestr(nargout, args):
    t = args[0]
    if type(t) is not DateTime:
        return NotImplemented
    from . import timefun
    return timefun.datestr(nargout, out(t.wall() / DAY + _EPOCH), *args[1:])


def _dt_weekday(nargout, args):
    t = args[0]
    if type(t) is not DateTime:
        return NotImplemented
    from . import timefun
    return timefun.weekday(nargout, out(t.wall() / DAY + _EPOCH), *args[1:])


DateTime.FUNCS.update(datenum=_dt_datenum, datevec=_dt_datevec, datestr=_dt_datestr, weekday=_dt_weekday)


def _dim(args, v, k=1):
    if len(args) > k and numel(args[k]) and opt_str(args[k]) is None:
        return ival(args[k]) - 1
    if len(args) > k and (opt_str(args[k]) or '').lower() == 'all':
        return 'all'
    return next((i for i, s in enumerate(v.shape) if s != 1), 0)


def _reduce(v, fn, args, keep_nan=True):
    """fn over a dimension of the key array (seconds)."""
    d = _dim(args, v)
    omit = any((opt_str(a) or '').lower() == 'omitnan' or (opt_str(a) or '').lower() == 'omitnat' for a in args[1:])
    a = v.a
    if d == 'all':
        a, d = a.reshape(-1, 1, order='F'), 0
    with np.errstate(all='ignore'):
        if omit:
            r = {'mean': np.nanmean, 'median': np.nanmedian, 'sum': np.nansum, 'std': np.nanstd}[fn](a, axis=d, keepdims=True)
        else:
            r = {'mean': np.mean, 'median': np.median, 'sum': np.sum, 'std': np.std}[fn](a, axis=d, keepdims=True)
    return r


def _mean_fn(kind):
    def f(nargout, args):
        v = args[0]
        if type(v) not in (DateTime, Duration):
            return NotImplemented
        r = _reduce(v, kind, args)
        if type(v) is DateTime:
            if kind == 'sum':
                raise err('MATLAB:sum:datetime', 'Datetimes cannot be added together.', 'sum')
            return DateTime(r, v.fmt, v.tz)
        if kind == 'std':
            return Duration(r, v.fmt)
        return Duration(r, v.fmt)
    return f


for _k in ('mean', 'median'):
    DateTime.FUNCS[_k] = _mean_fn(_k)
    Duration.FUNCS[_k] = _mean_fn(_k)
Duration.FUNCS['sum'] = _mean_fn('sum')
Duration.FUNCS['std'] = lambda nargout, args: Duration(np.std(args[0].a, ddof=1, axis=_dim(args, args[0], 2) if _dim(args, args[0], 2) != 'all' else None, keepdims=True), args[0].fmt) if type(args[0]) is Duration else NotImplemented


def _diff(nargout, args):
    v = args[0]
    if type(v) not in (DateTime, Duration):
        return NotImplemented
    n = ival(args[1]) if len(args) > 1 and numel(args[1]) else 1
    d = ival(args[2]) - 1 if len(args) > 2 else next((i for i, s in enumerate(v.shape) if s != 1), 0)
    r = np.diff(v.a, n=n, axis=d)
    return Duration(r, 'hh:mm:ss' if type(v) is DateTime else v.fmt)


DateTime.FUNCS['diff'] = _diff
Duration.FUNCS['diff'] = _diff


def _cumsum(nargout, args):
    v = args[0]
    if type(v) is not Duration:
        return NotImplemented
    d = _dim(args, v)
    return Duration(np.cumsum(v.a, axis=d if d != 'all' else None), v.fmt)


Duration.FUNCS['cumsum'] = _cumsum


def _elem(fn):
    def f(nargout, args):
        v = args[0]
        if type(v) is not Duration:
            return NotImplemented
        if fn in ('floor', 'ceil', 'round') and len(args) > 1:
            unit = sval(args[1], 'unit', fn).lower()
            u = {'years': 365.2425 * DAY, 'days': DAY, 'hours': 3600.0, 'minutes': 60.0, 'seconds': 1.0}.get(unit)
            if u is None:
                raise err(f'MATLAB:{fn}:InvalidUnit', "The unit is 'years', 'days', 'hours', 'minutes' or 'seconds'.", fn)
        else:
            u = 1.0
        g = {'floor': np.floor, 'ceil': np.ceil, 'round': lambda x: np.where(x >= 0, np.floor(x + 0.5), np.ceil(x - 0.5)), 'abs': np.abs}[fn]
        return Duration(g(v.a / u) * u, v.fmt)
    return f


for _k in ('floor', 'ceil', 'round', 'abs'):
    Duration.FUNCS[_k] = _elem(_k)


def _test(fn):
    def f(nargout, args):
        v = args[0]
        if type(v) is DateTime:
            if fn == 'isnan':
                raise err('MATLAB:isnan:datetime', 'Use isnat for datetimes.', 'isnan')
            return NotImplemented
        if type(v) is Duration:
            return _out_bool({'isnan': np.isnan, 'isinf': np.isinf, 'isfinite': np.isfinite}[fn](v.a))
        if type(v) is CalDuration:
            return _out_bool({'isnan': np.isnan, 'isinf': np.isinf, 'isfinite': np.isfinite}[fn](v.mo + v.d + v.t))
        return NotImplemented
    return f


for _k in ('isnan', 'isinf', 'isfinite'):
    for _cls in (DateTime, Duration, CalDuration):
        _cls.FUNCS[_k] = _test(_k)


def _modrem(fn):
    def f(nargout, args):
        a, b = args[0], args[1]
        if type(a) is not Duration:
            return NotImplemented
        bb = b.a if type(b) is Duration else np.asarray(darr(b), float)
        x, y = _bcast(a.a, bb)
        with np.errstate(all='ignore'):
            r = np.mod(x, y) if fn == 'mod' else np.fmod(x, y)
            if fn == 'mod':
                r = np.where(y == 0, x, r)
        return Duration(r, a.fmt)
    return f


Duration.FUNCS['mod'] = _modrem('mod')
Duration.FUNCS['rem'] = _modrem('rem')


def _linspace(nargout, args):
    a, b = args[0], args[1]
    o = a if isinstance(a, (DateTime, Duration)) else b
    A, B = o.coerce(a), o.coerce(b)
    n = ival(args[2]) if len(args) > 2 else 100
    x0, x1 = float(A.a.reshape(-1)[0]), float(B.a.reshape(-1)[0])
    vals = np.linspace(x0, x1, n).reshape(1, -1)
    return A.with_arrays(a=vals)


DateTime.FUNCS['linspace'] = _linspace
Duration.FUNCS['linspace'] = _linspace


def _split(nargout, args):
    v = args[0]
    if type(v) not in (CalDuration, Duration):
        return NotImplemented
    units = [u.lower() for u in (text_list(args[1]) if type(args[1]) in (Cell, Str) else [sval(args[1], 'units', 'split')])]
    res = []
    if type(v) is CalDuration:
        mo, d, t = v.mo.copy(), v.d.copy(), v.t.copy()
        for u in units:
            if u in ('years', 'year'):
                x = np.fix(mo / 12)
                mo = mo - 12 * x
            elif u in ('quarters', 'quarter'):
                x = np.fix(mo / 3)
                mo = mo - 3 * x
            elif u in ('months', 'month'):
                x, mo = mo, mo * 0
            elif u in ('weeks', 'week'):
                x = np.fix(d / 7)
                d = d - 7 * x
            elif u in ('days', 'day'):
                x, d = d, d * 0
            elif u == 'time':
                res.append(Duration(t))
                continue
            else:
                raise err('MATLAB:split:InvalidUnit', "The units are 'years', 'quarters', 'months', 'weeks', 'days' and 'time'.", 'split')
            res.append(out(x))
    else:
        x = v.a.copy()
        for u in units:
            secs = {'years': 365.2425 * DAY, 'days': DAY, 'hours': 3600.0, 'minutes': 60.0, 'seconds': 1.0}.get(u.rstrip('s') + 's')
            if secs is None:
                raise err('MATLAB:split:InvalidUnit', "The units are 'years', 'days', 'hours', 'minutes' and 'seconds'.", 'split')
            q = np.fix(x / secs) if u.rstrip('s') + 's' != units[-1].rstrip('s') + 's' else x / secs
            x = x - q * secs
            res.append(out(q))
    return tuple(res) if nargout > 1 else res[0]


CalDuration.FUNCS['split'] = _split
Duration.FUNCS['split'] = _split


def classes():
    return (DateTime, Duration, CalDuration)


def _plot_value(v):
    """A datetime or duration as numbers for the axes: date numbers (days) for
    datetimes, the duration in its display unit for durations."""
    if type(v) is DateTime:
        return v.wall() / DAY + _EPOCH, 'datetime'
    if type(v) is Duration:
        return v.a / DAY, 'duration:' + v.fmt
    return None, None


# ---- plotting datetimes and durations ------------------------------------------------------------------

# the functions whose data may be datetimes or durations, and which axes their data go on: a list per
# number of data inputs (positions 0, 1, 2 ...), the rest repeating in pairs (plot(x1, y1, x2, y2))
_PLOTS = {'plot': None, 'line': None, 'scatter': None, 'stairs': None, 'stem': None, 'bar': None, 'barh': 'h', 'area': None,
          'errorbar': None, 'semilogy': None, 'fill': None, 'plot3': 3, 'scatter3': 3, 'stem3': 3, 'histogram': 'x',
          'xline': 'x', 'yline': 'y', 'xlim': 'x', 'ylim': 'y', 'zlim': 'z', 'text': None}


def _axes_of(name, ndata):
    kind = _PLOTS[name]
    if kind in ('x', 'y', 'z'):
        return [kind] * ndata
    if kind == 3:
        return [('x', 'y', 'z')[k % 3] for k in range(ndata)]
    if ndata == 1:
        return ['x' if kind == 'h' else 'y']
    axes = [('x', 'y')[k % 2] for k in range(ndata)]
    if kind == 'h':
        # barh(x, y): the values run along x
        axes = [('y', 'x')[k % 2] for k in range(ndata)]
    return axes


def wrap_plots(reg):
    """The plotting functions take datetimes and durations: as date numbers
    (or days) on an axis whose ticks the figure labels as dates (or as
    durations)."""
    from . import Info
    for name in _PLOTS:
        info = reg.get(name)
        if info is None:
            continue

        def make(name, orig, ws, aw):
            def convert(args):
                kinds = {}
                if not any(type(a) in (DateTime, Duration) for a in args):
                    return args, kinds
                from ..graphics_base import GObj
                lead = 1 if args and isinstance(args[0], GObj) else 0
                data = []
                for a in args[lead:]:
                    if is_str(a) or type(a) is Cell:
                        break
                    data.append(a)
                axes = _axes_of(name, len(data))
                new = list(args)
                for k, a in enumerate(data):
                    vals, kind = _plot_value(a)
                    if kind:
                        new[lead + k] = out(vals)
                        kinds[axes[k]] = kind
                return tuple(new), kinds

            def mark(kinds, result):
                from . import graphics as G
                ax = None
                try:
                    ax = G.gca_()
                except Exception:
                    return
                cur = getattr(ax, 'kinds', None) or {}
                if ax.props.get('NextPlot') == 'replace' and name not in ('xlim', 'ylim', 'zlim', 'xline', 'yline', 'text'):
                    cur = {}
                cur.update(kinds)
                ax.kinds = cur
                ax.touch()
            if aw:
                async def f(*a):
                    pre = a[:2] if ws else a[:1]
                    args, kinds = convert(a[len(pre):])
                    r = await orig(*pre, *args)
                    if kinds or name not in ('xlim', 'ylim', 'zlim'):
                        mark(kinds, r)
                    return r
            else:
                def f(*a):
                    pre = a[:2] if ws else a[:1]
                    args, kinds = convert(a[len(pre):])
                    r = orig(*pre, *args)
                    if kinds or (len(args) > 0 and name not in ('xlim', 'ylim', 'zlim', 'xline', 'yline', 'text')):
                        mark(kinds, r)
                    return r
            return f
        reg[name] = Info(info.name, make(name, info.fn, info.ws, info.aw), info.ws, info.aw, info.nout, info.arr)

