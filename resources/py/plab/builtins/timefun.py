"""Dates and times as numbers: clock, now, datenum, datestr, datevec."""
import datetime as _dt
import math
import time

import numpy as np

from . import bi
from ._util import err, nargchk, arr, darr, out, opt_str, sval, num, is_str
from ..values import Char, Cell, Str, F64, text_list

_EPOCH = 719529.0      # datenum of 1970-01-01


def _dn_from_dt(d):
    return d.toordinal() + 366 + (d.hour * 3600 + d.minute * 60 + d.second + d.microsecond / 1e6) / 86400


def _dt_from_dn(x):
    days = math.floor(x)
    frac = x - days
    d = _dt.datetime.fromordinal(max(1, int(days) - 366))
    secs = round(frac * 86400 * 1e6) / 1e6
    return d + _dt.timedelta(seconds=secs)


@bi('clock')
def clock(nargout, *args):
    t = _dt.datetime.now()
    return out(np.array([[t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6]], F64))


@bi('now')
def now(nargout, *args):
    return _dn_from_dt(_dt.datetime.now())


@bi('date')
def date(nargout, *args):
    return Char.of(_dt.datetime.now().strftime('%d-%b-%Y'))


@bi('etime')
def etime(nargout, *args):
    a = darr(args[0]).reshape(-1)
    b = darr(args[1]).reshape(-1)
    da = _dt.datetime(int(a[0]), int(a[1]), int(a[2]), int(a[3]), int(a[4])) + _dt.timedelta(seconds=a[5])
    db = _dt.datetime(int(b[0]), int(b[1]), int(b[2]), int(b[3]), int(b[4])) + _dt.timedelta(seconds=b[5])
    return (db - da).total_seconds()


def _datenum_vec(row):
    y, mo, d = int(row[0]), row[1], row[2]
    h = row[3] if len(row) > 3 else 0
    mi = row[4] if len(row) > 4 else 0
    s = row[5] if len(row) > 5 else 0
    # months past 12 roll into years
    mo_i = int(mo)
    y += (mo_i - 1) // 12
    mo_i = (mo_i - 1) % 12 + 1
    base = _dt.date(y, mo_i, 1).toordinal() + 366 - 1
    return float(base + d + (h * 3600 + mi * 60 + s) / 86400)


_FORMATS = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d-%b-%Y %H:%M:%S', '%d-%b-%Y', '%m/%d/%Y', '%m/%d/%y', '%Y/%m/%d', '%H:%M:%S', '%d.%m.%Y']


@bi('datenum')
def datenum(nargout, *args):
    if not args:
        return now(1)
    if is_str(args[0]) or type(args[0]) is Cell:
        vals = []
        for s in text_list(args[0]):
            d = None
            for f in _FORMATS:
                try:
                    d = _dt.datetime.strptime(s.strip(), f)
                    break
                except ValueError:
                    continue
            if d is None:
                raise err('MATLAB:datenum:ConvertDateString', f"DATENUM failed. Unable to parse date string '{s}'.", 'datenum')
            vals.append(_dn_from_dt(d))
        return vals[0] if len(vals) == 1 else out(np.array(vals).reshape(-1, 1))
    if len(args) >= 3:
        cols = [darr(a).reshape(-1) for a in args]
        n = max(c.size for c in cols)
        cols = [np.resize(c, n) for c in cols]
        vals = [_datenum_vec([c[i] for c in cols]) for i in range(n)]
        return vals[0] if n == 1 else out(np.array(vals).reshape(darr(args[0]).shape))
    a = darr(args[0])
    if a.ndim == 2 and a.shape[1] in (3, 6):
        vals = [_datenum_vec(r) for r in a]
        return vals[0] if len(vals) == 1 else out(np.array(vals).reshape(-1, 1))
    return out(a)


@bi('datevec', nout=6)
def datevec(nargout, *args):
    v = args[0]
    if is_str(v) or type(v) is Cell:
        dn = datenum(1, v)
    else:
        dn = v
    a = darr(dn).reshape(-1)
    rows = []
    for x in a:
        d = _dt_from_dn(float(x))
        rows.append([d.year, d.month, d.day, d.hour, d.minute, d.second + d.microsecond / 1e6])
    m = np.array(rows, F64)
    if nargout <= 1:
        return out(m)
    return tuple(out(m[:, k:k + 1]) for k in range(min(nargout, 6)))


_DS = {0: '%d-%b-%Y %H:%M:%S', 1: '%d-%b-%Y', 2: '%m/%d/%y', 13: '%H:%M:%S', 23: '%m/%d/%Y', 29: '%Y-%m-%d', 30: '%Y%m%dT%H%M%S', 31: '%Y-%m-%d %H:%M:%S'}
_TOKENS = [('yyyy', '%Y'), ('yy', '%y'), ('mmmm', '%B'), ('mmm', '%b'), ('mm', '%m'), ('dddd', '%A'), ('ddd', '%a'), ('dd', '%d'),
           ('HH', '%H'), ('MM', '%M'), ('SS', '%S'), ('PM', '%p'), ('AM', '%p'), ('FFF', '%f3')]


def _fmt_from_pattern(p):
    out_s = ''
    i = 0
    while i < len(p):
        for tok, rep in _TOKENS:
            if p.startswith(tok, i):
                out_s += rep
                i += len(tok)
                break
        else:
            out_s += p[i]
            i += 1
    return out_s


@bi('datestr')
def datestr(nargout, *args):
    v = args[0] if args else now(1)
    if is_str(v):
        v = datenum(1, v)
    a = darr(v)
    if a.ndim == 2 and a.shape[1] in (3, 6) and a.shape[0] >= 1 and np.all(a[:, 0] > 1000) and a.shape[1] != 1:
        a = np.array([_datenum_vec(r) for r in a])
    fmt = None
    if len(args) > 1:
        f = args[1]
        fmt = _DS.get(int(num(f)), _DS[0]) if not is_str(f) else _fmt_from_pattern(sval(f, 'format', 'datestr'))
    strs = []
    for x in a.reshape(-1):
        d = _dt_from_dn(float(x))
        f = fmt or (_DS[1] if (float(x) == math.floor(float(x))) else _DS[0])
        s = d.strftime(f.replace('%f3', '%f')) if '%f3' in f else d.strftime(f)
        if '%f3' in f:
            s = s[:-3]
        strs.append(s)
    return Char.of(strs[0]) if len(strs) == 1 else Char.rows(strs)


@bi('weekday', nout=2)
def weekday(nargout, *args):
    dn = darr(args[0]).reshape(-1)
    n = [((int(math.floor(x)) - 2) % 7) + 1 for x in dn]
    names = [['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][k - 1] for k in n]
    r = float(n[0]) if len(n) == 1 else out(np.array(n, F64).reshape(-1, 1))
    if nargout >= 2:
        return r, Char.rows(names)
    return r


@bi('eomday')
def eomday(nargout, *args):
    import calendar
    y = darr(args[0]).reshape(-1)
    m = darr(args[1]).reshape(-1)
    n = max(y.size, m.size)
    r = [calendar.monthrange(int(np.resize(y, n)[i]), int(np.resize(m, n)[i]))[1] for i in range(n)]
    return float(r[0]) if n == 1 else out(np.array(r, F64).reshape(-1, 1))


@bi('leapyear')
def leapyear(nargout, *args):
    import calendar
    y = darr(args[0]).reshape(-1)
    r = [calendar.isleap(int(v)) for v in y]
    return r[0] if len(r) == 1 else out(np.array(r))


@bi('addtodate')
def addtodate(nargout, *args):
    d = num(args[0])
    q = num(args[1])
    f = sval(args[2], 'field', 'addtodate')
    mult = {'day': 1, 'hour': 1 / 24, 'minute': 1 / 1440, 'second': 1 / 86400, 'millisecond': 1 / 86400000, 'week': 7}.get(f)
    if mult is not None:
        return d + q * mult
    v = list(darr(datevec(1, d)).reshape(-1))
    if f == 'month':
        v[1] += q
    elif f == 'year':
        v[0] += q
    return _datenum_vec(v)
