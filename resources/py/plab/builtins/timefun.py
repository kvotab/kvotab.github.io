"""Dates and times as numbers: clock, now, datenum, datestr, datevec,
weekday, eomday, leapyear, addtodate.

A date number counts days from 1 January of year 0 (that day is 1), in the
proleptic Gregorian calendar, with the time of day as the fraction. The
calendar arithmetic is done here (days to and from civil dates, as Howard
Hinnant's algorithms do it), so that year 0 and the years before it work.
"""
import datetime as _dt
import re

import numpy as np

from . import bi
from ._util import err, nargchk, arr, darr, out, opt_str, sval, num, is_str
from ..values import Char, Cell, Str, F64, text_list

_EPOCH = 719529          # the date number of 1970-01-01
_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
_DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']


# ---- days and civil dates ----------------------------------------------------------------------------

def _days_from_civil(y, m, d):
    """Days from 1970-01-01 to the date y-m-d (arrays of whole numbers; m 1 to 12)."""
    y = np.asarray(y, np.int64) - (np.asarray(m) <= 2)
    era = np.floor_divide(y, 400)
    yoe = y - era * 400
    mp = (np.asarray(m, np.int64) + 9) % 12
    doy = (153 * mp + 2) // 5 + np.asarray(d, np.int64) - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def _civil_from_days(z):
    """Year, month and day of the days z from 1970-01-01 (whole numbers)."""
    z = np.asarray(z, np.int64) + 719468
    era = np.floor_divide(z, 146097)
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = np.where(mp < 10, mp + 3, mp - 9)
    return y + (m <= 2), m, d


def _is_leap(y):
    y = np.asarray(y, np.int64)
    return (y % 4 == 0) & ((y % 100 != 0) | (y % 400 == 0))


def _month_days(y, m):
    md = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
    m = np.asarray(m, np.int64)
    return md[m - 1] + ((m == 2) & _is_leap(y))


def _datenum_parts(y, mo, d, h=0.0, mi=0.0, s=0.0):
    """Date numbers of year, month, day, hour, minute and second arrays: months
    past 12 (or below 1) roll into the years; a fraction of a year or month adds
    that part of its days; days, hours, minutes and seconds may run past their
    ranges."""
    y, mo, d, h, mi, s = np.broadcast_arrays(*[np.asarray(v, F64) for v in (y, mo, d, h, mi, s)])
    yi = np.floor(y)
    fy = y - yi
    mi_ = np.floor(mo)
    fm = mo - mi_
    yi = yi + np.floor_divide(mi_ - 1, 12)
    mi_ = np.mod(mi_ - 1, 12) + 1
    days = _days_from_civil(yi, mi_, 1).astype(F64) + _EPOCH - 1 + d
    days = days + fm * _month_days(yi, mi_)
    days = days + fy * np.where(_is_leap(yi), 366, 365)
    return days + (h * 3600 + mi * 60 + s) / 86400


def _datevec_rows(dn):
    """N-by-6 [year month day hour minute seconds] of date numbers, the seconds
    rounded to what the number can hold (about 1e-5 s today)."""
    dn = np.asarray(dn, F64).reshape(-1)
    day = np.floor(dn)
    secs = (dn - day) * 86400
    with np.errstate(all='ignore'):
        res = np.spacing(np.abs(dn)) * 86400
        dec = np.clip(-np.ceil(np.log10(np.where(res > 0, res, 1e-12))), 0, 9)
    secs = np.array([round(s_, int(k)) for s_, k in zip(secs, dec)]) if secs.size else secs
    carry = secs >= 86400
    day = day + carry
    secs = np.where(carry, secs - 86400, secs)
    y, m, d = _civil_from_days(day.astype(np.int64) - _EPOCH)
    h = np.floor(secs / 3600)
    mi = np.floor((secs - h * 3600) / 60)
    s = secs - h * 3600 - mi * 60
    s = np.where(np.abs(s - np.round(s)) < 1e-9, np.round(s), s)
    return np.column_stack([y, m, d, h, mi, s]).astype(F64)


# ---- reading dates in text ------------------------------------------------------------------------

_TOKEN_RE = [('yyyy', r'(?P<y>[+-]?\d{4})'), ('yy', r'(?P<yy>\d{2})'), ('mmmm', r'(?P<mon>[A-Za-z]+)'), ('mmm', r'(?P<mon>[A-Za-z]{3})'),
             ('mm', r'(?P<m>\d{1,2})'), ('dddd', r'[A-Za-z]+'), ('ddd', r'[A-Za-z]{3}'), ('dd', r'(?P<d>\d{1,2})'),
             ('HH', r'(?P<H>\d{1,2})'), ('MM', r'(?P<M>\d{1,2})'), ('SS', r'(?P<S>\d{1,2})'), ('FFF', r'(?P<F>\d{1,6})'),
             ('PM', r'(?P<p>[AaPp][Mm])'), ('AM', r'(?P<p>[AaPp][Mm])')]

# the formats tried in turn for text without one (the language's standard ones and their kin)
_STD = ['dd-mmm-yyyy HH:MM:SS', 'dd-mmm-yyyy HH:MM', 'dd-mmm-yyyy', 'yyyy-mm-dd HH:MM:SS', 'yyyy-mm-dd HH:MM', 'yyyy-mm-dd',
        'yyyy/mm/dd HH:MM:SS', 'yyyy/mm/dd', 'mm/dd/yyyy HH:MM:SS', 'mm/dd/yyyy HH:MM', 'mm/dd/yyyy', 'mm/dd/yy', 'mm/dd',
        'mmm-dd-yyyy HH:MM:SS', 'mmm-dd-yyyy', 'dd mmm yyyy HH:MM:SS', 'dd mmm yyyy', 'mmm dd yyyy HH:MM:SS', 'mmm dd yyyy',
        'dd.mmm.yyyy HH:MM:SS', 'dd.mmm.yyyy', 'mmm.dd.yyyy HH:MM:SS', 'mmm.dd.yyyy', 'mmm.dd,yyyy HH:MM:SS', 'mmm.dd,yyyy',
        'yyyy-mm-ddTHH:MM:SS.FFFZ', 'yyyy-mm-ddTHH:MM:SSZ', 'yyyy-mm-ddTHH:MM:SS', 'yyyy-mm', 'yyyymmddTHHMMSS', 'yyyymmdd', 'HH:MM:SS PM', 'HH:MM:SS', 'HH:MM PM', 'HH:MM', 'mmmyy', 'yyyy', 'dd.mm.yyyy']


def _pattern_regex(fmt):
    out_s, i = '', 0
    while i < len(fmt):
        for tok, rx in _TOKEN_RE:
            if fmt.startswith(tok, i):
                out_s += rx
                i += len(tok)
                break
        else:
            c = fmt[i]
            out_s += r'\s*' if c == ' ' else re.escape(c)
            i += 1
    if 'FFF' not in fmt:
        out_s = out_s.replace(r'(?P<S>\d{1,2})', r'(?P<S>\d{1,2}(?:\.\d+)?)')
    # a name may be given twice (mmmm and mmm): keep the first
    seen = set()

    def dedupe(m):
        name = m.group(1)
        if name in seen:
            return '(?:'
        seen.add(name)
        return m.group(0)
    return re.sub(r'\(\?P<(\w+)>', dedupe, out_s)


def _parse_date(s, fmt=None):
    """[y mo d h mi s] of a date in text, by its format or by the standard ones."""
    s = s.strip()
    fmts = [fmt] if fmt else _STD
    today = _dt.date.today()
    for f in fmts:
        rx = _pattern_regex(f)
        m = re.match(rx + (r'' if fmt else r'\s*$'), s, re.I)
        if not m:
            continue
        g = m.groupdict()
        try:
            if g.get('mon'):
                name = g['mon'].lower()
                mo = next(k + 1 for k, n in enumerate(_MONTHS) if n.lower().startswith(name[:3]) and (len(name) <= 3 or n.lower() == name))
            elif g.get('m'):
                mo = int(g['m'])
            else:
                mo = 1 if (g.get('y') or g.get('yy') or g.get('H')) else today.month
        except StopIteration:
            continue
        if g.get('y'):
            y = int(g['y'])
        elif g.get('yy'):
            yy = int(g['yy'])
            pivot = today.year - 50              # two digits: the 100 years from 50 years ago
            y = pivot - pivot % 100 + yy
            if y < pivot:
                y += 100
        else:
            y = today.year
        d = int(g['d']) if g.get('d') else 1
        H = int(g['H']) if g.get('H') else 0
        M = int(g['M']) if g.get('M') else 0
        S = float(g['S']) if g.get('S') else 0.0
        if g.get('F'):
            S += float('0.' + g['F'])
        if g.get('p'):
            pm = g['p'].lower() == 'pm'
            H = (H % 12) + (12 if pm else 0)
        if not (1 <= mo <= 12 and 1 <= d <= 31 and H <= 24 and M < 60 and S < 61):
            continue
        return [y, mo, d, H, M, S]
    raise err('MATLAB:datenum:ConvertDateString', f"DATENUM failed. Unable to parse date string '{s}'.", 'datenum')


def _text_rows(v, fmt=None):
    """Date vectors of dates in text, as written; a day past its month's end
    or an hour of 24 carries into the next field."""
    m = np.array([_parse_date(s, fmt) for s in text_list(v)], F64).reshape(-1, 6)
    if m.size:
        over = (m[:, 2] > _month_days(m[:, 0], m[:, 1].astype(np.int64))) | (m[:, 3] >= 24) | (m[:, 5] >= 60)
        if np.any(over):
            m[over] = _datevec_rows(_datenum_parts(*[m[over, k] for k in range(6)]))
    return m


# ---- the functions -------------------------------------------------------------------------------------

@bi('clock')
def clock(nargout, *args):
    t = _dt.datetime.now()
    return out(np.array([[t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6]], F64))


@bi('now')
def now(nargout, *args):
    t = _dt.datetime.now()
    return float(_datenum_parts(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6))


@bi('date')
def date(nargout, *args):
    return Char.of(_dt.datetime.now().strftime('%d-%b-%Y'))


@bi('etime')
def etime(nargout, *args):
    """etime(t1, t0): the seconds from date vector t0 to t1 (etime(clock, t0)
    is the time since t0)."""
    nargchk(args, 2, 2, 'etime')
    if any(darr(v).size == 0 or darr(v).size % 6 for v in args):
        raise err('MATLAB:etime:InvalidInput', 'The inputs are date vectors [y m d h mi s] (or rows of them).', 'etime')
    a = darr(args[0]).reshape(-1, 6)
    b = darr(args[1]).reshape(-1, 6)
    # whole days apart, then the times of day: no rounding through date numbers
    da = _datenum_parts(a[:, 0], a[:, 1], a[:, 2])
    db = _datenum_parts(b[:, 0], b[:, 1], b[:, 2])
    r = (da - db) * 86400 + (a[:, 3:6] - b[:, 3:6]) @ np.array([3600.0, 60.0, 1.0])
    return float(r[0]) if r.size == 1 else out(r.reshape(-1, 1))


def _datenum_vec(row):
    return float(_datenum_parts(*(list(row) + [0.0] * (6 - len(row)))[:6]))


@bi('datenum')
def datenum(nargout, *args):
    if not args:
        return now(1)
    if is_str(args[0]) or type(args[0]) is Cell:
        fmt = sval(args[1], 'format', 'datenum') if len(args) > 1 and is_str(args[1]) else None
        rows = _text_rows(args[0], fmt)
        vals = _datenum_parts(*[rows[:, k] for k in range(6)])
        return float(vals[0]) if vals.size == 1 else out(vals.reshape(-1, 1))
    if len(args) >= 3:
        arrs = [darr(a) for a in args[:6]]
        big = [a for a in arrs if a.size != 1]
        shape = big[0].shape if big else (1, 1)
        if any(a.shape != shape for a in big):
            raise err('MATLAB:datenum:InputDims', 'The date parts must be scalars or arrays of the same size.', 'datenum')
        r = _datenum_parts(*[a.reshape(shape) if a.size != 1 else a.reshape(()) for a in arrs])
        return float(r.reshape(-1)[0]) if r.size == 1 else out(np.asarray(r).reshape(shape))
    a = darr(args[0])
    if a.ndim == 2 and a.shape[1] in (3, 6) and a.size:
        r = _datenum_parts(*[a[:, k] for k in range(a.shape[1])])
        return float(r[0]) if r.size == 1 else out(r.reshape(-1, 1))
    return out(a)


@bi('datevec', nout=6)
def datevec(nargout, *args):
    v = args[0]
    shape = None
    if is_str(v) or type(v) is Cell:
        fmt = sval(args[1], 'format', 'datevec') if len(args) > 1 and is_str(args[1]) else None
        m = _text_rows(v, fmt)
    else:
        a = darr(v)
        shape = a.shape
        m = _datevec_rows(a.reshape(-1, order='F'))
    if nargout <= 1:
        return out(m)
    cols = [m[:, k] for k in range(6)]
    if shape is not None:
        cols = [c.reshape(shape, order='F') for c in cols]
    else:
        cols = [c.reshape(-1, 1) for c in cols]
    return tuple(out(c) for c in cols[:min(nargout, 6)])


_DS = {0: 'dd-mmm-yyyy HH:MM:SS', 1: 'dd-mmm-yyyy', 2: 'mm/dd/yy', 3: 'mmm', 4: 'm', 5: 'mm', 6: 'mm/dd', 7: 'dd', 8: 'ddd', 9: 'd',
       10: 'yyyy', 11: 'yy', 12: 'mmmyy', 13: 'HH:MM:SS', 14: 'HH:MM:SS PM', 15: 'HH:MM', 16: 'HH:MM PM', 17: 'QQ-YY', 18: 'QQ',
       19: 'dd/mm', 20: 'dd/mm/yy', 21: 'mmm.dd,yyyy HH:MM:SS', 22: 'mmm.dd,yyyy', 23: 'mm/dd/yyyy', 24: 'dd/mm/yyyy', 25: 'yy/mm/dd',
       26: 'yyyy/mm/dd', 27: 'QQ-YYYY', 28: 'mmmyyyy', 29: 'yyyy-mm-dd', 30: 'yyyymmddTHHMMSS', 31: 'yyyy-mm-dd HH:MM:SS'}
_FMT_TOKENS = ['yyyy', 'YYYY', 'yy', 'YY', 'mmmm', 'mmm', 'mm', 'm', 'dddd', 'ddd', 'dd', 'd', 'HH', 'MM', 'SS', 'FFF', 'AM', 'PM', 'QQ']


def _ms_rows(rows):
    """Date vectors rounded to whole milliseconds, a rounding up to the next
    second, minute or day carried in whole numbers."""
    day = _days_from_civil(rows[:, 0], rows[:, 1], rows[:, 2])
    ms = np.round((rows[:, 3] * 3600 + rows[:, 4] * 60 + rows[:, 5]) * 1000).astype(np.int64)
    day = day + np.floor_divide(ms, 86400000)
    ms = np.mod(ms, 86400000)
    y, m, d = _civil_from_days(day)
    return np.column_stack([y, m, d, ms // 3600000, (ms // 60000) % 60, (ms % 60000) / 1000]).astype(F64)


def _format_date(row, fmt):
    """A date vector written by the language's date format (yyyy, mmm, dd,
    HH, MM, SS, FFF, PM, QQ and the like)."""
    y, mo, d, H, M, S = row
    y, mo, d, H, M = int(y), int(mo), int(d), int(H), int(M)
    wd = int((_days_from_civil(y, mo, d) + 4) % 7)          # 1970-01-01 was a Thursday
    ampm = 'AM' in fmt or 'PM' in fmt
    out_s, i = '', 0
    while i < len(fmt):
        for tok in _FMT_TOKENS:
            if fmt.startswith(tok, i):
                t = tok
                break
        else:
            out_s += fmt[i]
            i += 1
            continue
        i += len(t)
        if t in ('yyyy', 'YYYY'):
            out_s += f'{y:04d}'
        elif t in ('yy', 'YY'):
            out_s += f'{y % 100:02d}'
        elif t == 'mmmm':
            out_s += _MONTHS[mo - 1]
        elif t == 'mmm':
            out_s += _MONTHS[mo - 1][:3]
        elif t == 'mm':
            out_s += f'{mo:02d}'
        elif t == 'm':
            out_s += _MONTHS[mo - 1][0]
        elif t == 'dddd':
            out_s += _DAYS[wd]
        elif t == 'ddd':
            out_s += _DAYS[wd][:3]
        elif t == 'dd':
            out_s += f'{d:02d}'
        elif t == 'd':
            out_s += _DAYS[wd][0]
        elif t == 'HH':
            out_s += f'{(H % 12 or 12) if ampm else H:2d}' if ampm else f'{H:02d}'
        elif t == 'MM':
            out_s += f'{M:02d}'
        elif t == 'SS':
            out_s += f'{int(S):02d}'
        elif t == 'FFF':
            out_s += f'{int(round(S * 1000)) % 1000:03d}'
        elif t in ('AM', 'PM'):
            out_s += 'PM' if H >= 12 else 'AM'
        elif t == 'QQ':
            out_s += f'Q{(mo - 1) // 3 + 1}'
    return out_s


@bi('datestr')
def datestr(nargout, *args):
    nargchk(args, 1, 3, 'datestr')
    v = args[0]
    if is_str(v) or type(v) is Cell:
        rows = _text_rows(v)
    else:
        a = darr(v)
        if a.ndim == 2 and a.shape[1] in (3, 6) and a.size and np.all(a[:, 0] > 1000) and np.all(np.abs(a[:, 1]) <= 12):
            a6 = np.zeros((a.shape[0], 6))
            a6[:, :a.shape[1]] = a
            rows = _datevec_rows(_datenum_parts(*[a6[:, k] for k in range(6)]))
        else:
            rows = _datevec_rows(a.reshape(-1, order='F'))
    fmt = None
    if len(args) > 1:
        f = args[1]
        fmt = _DS.get(int(num(f)), _DS[0]) if not is_str(f) else sval(f, 'format', 'datestr')
    rows = _ms_rows(rows)
    if fmt is None:
        fmt = _DS[1] if np.all(rows[:, 3:] == 0) else _DS[0]
    strs = [_format_date(r, fmt) for r in rows]
    return Char.of(strs[0]) if len(strs) == 1 else Char.rows(strs)


@bi('weekday', nout=2)
def weekday(nargout, *args):
    v = args[0]
    if is_str(v) or type(v) is Cell:
        rows = _text_rows(v)
        dn = _datenum_parts(*[rows[:, k] for k in range(6)])
        shape = (dn.size, 1)
    else:
        a = darr(v)
        dn, shape = a.reshape(-1, order='F'), a.shape
    n = (np.floor(dn).astype(np.int64) - 2) % 7 + 1
    r = float(n[0]) if n.size == 1 else out(n.astype(F64).reshape(shape, order='F'))
    if nargout >= 2:
        long_ = len(args) > 1 and (opt_str(args[1]) or '').lower() == 'long'
        names = [_DAYS[k - 1] if long_ else _DAYS[k - 1][:3] for k in n]
        return r, Char.rows(names)
    return r


@bi('eomday')
def eomday(nargout, *args):
    nargchk(args, 2, 2, 'eomday')
    y, m = np.broadcast_arrays(darr(args[0]), darr(args[1]))
    if np.any((m < 1) | (m > 12)):
        raise err('MATLAB:eomday:InvalidMonth', 'The month must be from 1 to 12.', 'eomday')
    r = _month_days(np.floor(y), m.astype(np.int64)).astype(F64)
    return float(r.reshape(-1)[0]) if r.size == 1 else out(r)


@bi('leapyear')
def leapyear(nargout, *args):
    y = darr(args[0])
    r = _is_leap(np.floor(y))
    return bool(r.reshape(-1)[0]) if r.size == 1 else out(r)


@bi('addtodate')
def addtodate(nargout, *args):
    """A quantity of a date field added to date numbers: days, weeks, hours,
    minutes, seconds and milliseconds as fractions of a day; months and years
    to the date vector (a day past the month's end goes to its last day)."""
    nargchk(args, 3, 3, 'addtodate')
    d = darr(args[0])
    q = darr(args[1])
    f = sval(args[2], 'field', 'addtodate').lower()
    d, q = np.broadcast_arrays(d, q)
    mult = {'day': 1, 'hour': 1 / 24, 'minute': 1 / 1440, 'second': 1 / 86400, 'millisecond': 1 / 86400000, 'week': 7}.get(f)
    if mult is not None:
        r = d + q * mult
    elif f in ('month', 'year'):
        if np.any(q != np.floor(q)):
            raise err('MATLAB:addtodate:NonIntegerQuantity', 'Months and years are added in whole numbers.', 'addtodate')
        rows = _datevec_rows(d.reshape(-1, order='F'))
        qq = q.reshape(-1, order='F') * (12 if f == 'year' else 1)
        mo = rows[:, 1] - 1 + qq
        y = rows[:, 0] + np.floor_divide(mo, 12)
        mo = np.mod(mo, 12) + 1
        day = np.minimum(rows[:, 2], _month_days(y, mo.astype(np.int64)))
        r = _datenum_parts(y, mo, day, rows[:, 3], rows[:, 4], rows[:, 5]).reshape(d.shape, order='F')
    else:
        raise err('MATLAB:addtodate:InvalidField', "The field is 'year', 'month', 'week', 'day', 'hour', 'minute', 'second' or 'millisecond'.", 'addtodate')
    r = np.asarray(r, F64)
    return float(r.reshape(-1)[0]) if r.size == 1 else out(r)
