"""The value classes datetime, duration, calendarDuration, categorical,
table and timetable, run natively (CPython with numpy and scipy). The
expected values are worked out by hand or with Python's datetime module.

    python3 test_types.py          (from any folder)
"""
import asyncio
import datetime as dt
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char, Cell, Str  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-types-')


def run(code):
    R.BASE.clear()
    R.BASE.gnames.clear()
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


def v(x):
    if isinstance(x, (bool, float, int, complex)):
        return np.array([x])
    return np.asarray(x).reshape(-1, order='F')


def near(label, got, want, tol=1e-9):
    g = np.concatenate([v(x) for x in got]) if isinstance(got, tuple) else v(got)
    w = np.asarray(want, dtype=float).reshape(-1)
    ok = g.shape == w.shape and np.allclose(g.astype(float), w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {g.tolist()}, want {w.tolist()}')


def text(x):
    if isinstance(x, Char):
        return x.str() if x.a.shape[0] <= 1 else x.row_strs()
    if isinstance(x, Cell):
        return [text(e) for e in x.a.reshape(-1, order='F')]
    if isinstance(x, Str):
        return list(x.a.reshape(-1, order='F'))
    return x


def same(label, got, want):
    got = text(got)
    return C(label, got == want, f'got {got!r}, want {want!r}')


def err_of(code):
    W, _ = run(f"try\n{code}\nm = 'none';\ncatch e\nm = e.message;\nend")
    return text(W['m'])


def posix(*a):
    return (dt.datetime(*a) - dt.datetime(1970, 1, 1)).total_seconds()


def datenum(*a):
    d = dt.datetime(*a)
    return d.toordinal() + 366 + (d - dt.datetime(d.year, d.month, d.day)).total_seconds() / 86400


# ---- datetime ------------------------------------------------------------------------------------------
W, o = run("""t = datetime(2026, 11, 3); s1 = char(t);
t2 = datetime(2026, 11, 3, 14, 5, 30); s2 = char(t2);
p = posixtime(t2); n = datenum(t2); y = t2.Year; mo = t2.Month; h = t2.Hour;
d = t2 - t; dh = hours(d); cls = class(d);
t3 = t2 + hours(1.5); s3 = char(t3);
e = datetime(2026, 1, 31) + calmonths(1); se = char(e);
f = datetime(2024, 2, 29) + calyears(1); sf = char(f);
b = between(datetime(2026,1,15), datetime(2027,3,20)); sb = char(b);
x = [t t2 t3]; nx = numel(x); x(2) = []; nx2 = numel(x);
srt = sort([t3 t t2], 'descend'); first = char(srt(1));
[mx, im] = max([t t3 t2]);
nat = isnat([t NaT]);
r = t:caldays(1):datetime(2026, 11, 6); nr = numel(r); rl = char(r(end));
dd = datetime(2026,1,1):hours(6):datetime(2026,1,2); ndd = numel(dd);
iso = char(datetime('2026-11-03T14:05:06'));
fmt = char(datetime('03/11/2026', 'InputFormat', 'dd/MM/yyyy'));
ymd8 = char(datetime(20261103, 'ConvertFrom', 'yyyymmdd'));
fromdn = char(datetime(738000, 'ConvertFrom', 'datenum'));
t.Format = 'yyyy-MM-dd'; sfmt = char(t);
x2 = datetime(2026,3,15,10,30,0); x2.Format = 'eeee, MMMM d, uuuu h:mm a'; long = char(x2);
ds1 = char(dateshift(datetime(2026,3,15,10,30,0), 'start', 'month'));
ds2 = char(dateshift(datetime(2026,3,15,10,30,0), 'dayofweek', 'Monday'));
ds3 = char(dateshift(datetime(2026,2,14,9,5,30), 'end', 'month')); ds4 = char(dateshift(datetime(2026,2,14,9,5,30), 'end', 'quarter'));
ds5 = char(dateshift(datetime(2026,2,14,9,5,30), 'end', 'week')); ds6 = char(dateshift(datetime(2026,2,14,9,5,30), 'end', 'day'));
wk = isweekend(datetime(2026,11,7)); q = quarter(datetime(2026,8,1));
z = datetime(2026, 6, 1, 12, 0, 0, 'TimeZone', 'UTC'); z.TimeZone = 'Europe/Stockholm'; sz = char(z); zp = posixtime(z);
[tzd, tzs] = tzoffset(datetime(2026, [1 7], 1, 12, 0, 0, 'TimeZone', 'Europe/Stockholm')); tzh = [hours(tzd) hours(tzs)];
[tzd, tzs] = tzoffset(datetime(2026, [1 7], 1, 12, 0, 0, 'TimeZone', 'Australia/Sydney')); tzsyd = [hours(tzd) hours(tzs)];
m2 = datetime(2026, 13, 1); sm2 = char(m2);
eq = datetime(2026,1,3) == '2026-01-03';
""")
same('datetime(y, m, d) shows the date alone', W['s1'], '03-Nov-2026')
same('datetime with a time shows date and time', W['s2'], '03-Nov-2026 14:05:30')
near('posixtime: seconds since 1970', W['p'], posix(2026, 11, 3, 14, 5, 30))
near('datenum of a datetime', W['n'], datenum(2026, 11, 3, 14, 5, 30), 1e-12)
near('Year, Month, Hour', (W['y'], W['mo'], W['h']), [2026, 11, 14])
C('datetime minus datetime is a duration', text(W['cls']) == 'duration', W['cls'])
near('... of 14 h 5 min 30 s', W['dh'], 14 + 5 / 60 + 30 / 3600)
same('plus hours(1.5)', W['s3'], '03-Nov-2026 15:35:30')
same('31 January plus a calendar month is the last day of February', W['se'], '28-Feb-2026')
same('29 February plus a calendar year is 28 February', W['sf'], '28-Feb-2025')
same('between: years, months, days', W['sb'], '1y 2mo 5d')
near('deleting an element', (W['nx'], W['nx2']), [3, 2])
same("sort 'descend' puts the latest first", W['first'], '03-Nov-2026 15:35:30')
near('max: its position', W['im'], 2)
near('isnat', W['nat'], [0, 1])
near('a range by calendar days: 4 days', W['nr'], 4)
same('... ending on the 6th', W['rl'], '06-Nov-2026')
near('a range by 6 hours over a day: 5 times', W['ndd'], 5)
same('ISO 8601 text', W['iso'], '03-Nov-2026 14:05:06')
same('InputFormat', W['fmt'], '03-Nov-2026')
same("ConvertFrom 'yyyymmdd'", W['ymd8'], '03-Nov-2026')
same("ConvertFrom 'datenum'", W['fromdn'], dt.date.fromordinal(738000 - 366).strftime('%d-%b-%Y') + ' 00:00:00')
same('Format set', W['sfmt'], '2026-11-03')
same('long names, 12-hour clock', W['long'], 'Sunday, March 15, 2026 10:30 AM')
same("dateshift 'start' of the month", W['ds1'], '01-Mar-2026 00:00:00')
same("dateshift to the next Monday", W['ds2'], '16-Mar-2026 10:30:00')
same("dateshift 'end' of a month is its last day", W['ds3'], '28-Feb-2026 00:00:00')
same("dateshift 'end' of a quarter is its last day", W['ds4'], '31-Mar-2026 00:00:00')
same("dateshift 'end' of a week is its Saturday", W['ds5'], '14-Feb-2026 00:00:00')
same("dateshift 'end' of a day is the next day's start", W['ds6'], '15-Feb-2026 00:00:00')
C('7 November 2026 is a Saturday', W['wk'] is True or bool(np.all(v(W['wk']))), W['wk'])
near('quarter of August', W['q'], 3)
same('a UTC time shown in Stockholm (summer time)', W['sz'], '01-Jun-2026 14:00:00')
near('... the same instant', W['zp'], posix(2026, 6, 1, 12, 0, 0))
near("tzoffset in Stockholm: 1 and 2 hours, the second's summer time 1 hour", W['tzh'], [1, 2, 0, 1])
near('... and in Sydney, whose summer is in January', W['tzsyd'], [11, 10, 1, 0])
same('month 13 carries into the next year', W['sm2'], '01-Jan-2027')
C('a datetime compares with text', bool(np.all(v(W['eq']))), W['eq'])

# ---- duration and calendarDuration ------------------------------------------------------------------
W, o = run("""d = hours(3); m = minutes(d); s1 = char(d * 2); r = d / hours(1); s2 = char(-d);
d2 = duration(1, 30, 15); s3 = char(d2); sec = seconds(d2);
d3 = duration('01:30:00'); m3 = minutes(d3);
y = years(1); dy = days(y);
mm = minutes(90); mm.Format = 'hh:mm'; s4 = char(mm);
avg = char(mean([hours(1) hours(2)]));
tot = char(sum([hours(1) minutes(30)]));
[lo, i] = min([hours(2) hours(1) NaN*hours(1)]); slo = char(lo);
c = calmonths(14); sc = char(c);
c2 = calmonths(2) + caldays(3); sc2 = char(c2);
tf = isduration(d); tc = iscalendarduration(c);
""")
near('minutes of 3 hours', W['m'], 180)
same('a duration times 2 keeps its unit', W['s1'], '6 hr')
near('a duration over a duration is a number', W['r'], 3)
same('minus', W['s2'], '-3 hr')
same('duration(h, m, s)', W['s3'], '01:30:15')
near('... in seconds', W['sec'], 5415)
near('duration from text', W['m3'], 90)
near('a year of durations is 365.2425 days', W['dy'], 365.2425)
same("Format 'hh:mm'", W['s4'], '01:30')
same('mean of durations', W['avg'], '1.5 hr')
same('sum of durations, in the first one\'s unit', W['tot'], '1.5 hr')
same('min of durations', W['slo'], '1 hr')
near('... its position', W['i'], 2)
same('14 calendar months show as a year and two months', W['sc'], '1y 2mo')
same('months plus days', W['sc2'], '2mo 3d')
C('isduration, iscalendarduration', W['tf'] is True and W['tc'] is True, (W['tf'], W['tc']))

# ---- categorical --------------------------------------------------------------------------------------
W, o = run("""c = categorical({'red', 'green', 'red', 'blue', ''});
k = categories(c); n = countcats(c); u = isundefined(c); e = c == 'red';
c(2) = 'yellow'; k2 = categories(c);
s = categorical([3 1 2 3], [1 2 3], {'low', 'mid', 'high'}, 'Ordinal', true);
gt = s > 'low'; mx = char(max(s)); sd = double(s); sc = cellstr(s);
c3 = mergecats(c, {'red', 'yellow'}, 'warm'); k3 = categories(c3);
c4 = renamecats(c, 'green', 'verde'); k4 = categories(c4);
c5 = reordercats(categorical({'b', 'a', 'c'}), {'c', 'a', 'b'}); k5 = categories(c5);
c6 = removecats(c, 'blue'); u6 = isundefined(c6);
x = [c categorical({'pink'})]; kx = categories(x);
m = ismember(c, {'red', 'blue'});
p = categorical({'a'}, {'a', 'b'}, 'Protected', true);
[g, gn] = findgroups(categorical({'y', 'x', 'y'}));
""")
same('categories: sorted, the empty text left out', W['k'], ['blue', 'green', 'red'])
near('countcats', W['n'], [1, 1, 2])
near('isundefined: the empty text', W['u'], [0, 0, 0, 0, 1])
near("c == 'red'", W['e'], [1, 0, 1, 0, 0])
same('assigning a new name adds a category', W['k2'], ['blue', 'green', 'red', 'yellow'])
near('ordinal: > compares by the order of the categories', W['gt'], [1, 0, 1, 1])
same('max of an ordinal array', W['mx'], 'high')
near('double gives the codes', W['sd'], [3, 1, 2, 3])
same('cellstr gives the names', W['sc'], ['high', 'low', 'mid', 'high'])
same('mergecats', W['k3'], ['blue', 'green', 'warm'])
same('renamecats', W['k4'], ['blue', 'verde', 'red', 'yellow'])
same('reordercats by names', W['k5'], ['c', 'a', 'b'])
near('removecats makes its elements undefined', W['u6'], [0, 0, 0, 1, 1])
same('concatenation joins the categories', W['kx'], ['blue', 'green', 'red', 'yellow', 'pink'])
near('ismember with names', W['m'], [1, 0, 1, 1, 0])
near('findgroups: groups in the order of the categories', W['g'], [2, 1, 2])
C('a protected array refuses a new category', 'categor' in err_of("p = categorical({'a'}, {'a', 'b'}, 'Protected', true); p(2) = 'z';").lower(),
  err_of("p = categorical({'a'}, {'a', 'b'}, 'Protected', true); p(2) = 'z';"))
C('< needs an ordinal array', err_of("c = categorical({'a', 'b'}); t = c(1) < c(2);") != 'none', err_of("c = categorical({'a', 'b'}); t = c(1) < c(2);"))

# ---- table: making, indexing, assigning ------------------------------------------------------------
W, o = run("""Name = {'Ann'; 'Bo'; 'Cy'}; Age = [38; 43; 38]; Ok = [true; false; true];
T = table(Name, Age, Ok);
vn = T.Properties.VariableNames; sz = size(T); h = height(T); w = width(T);
a = T.Age; b = T{2, 'Name'}; c = T{:, {'Age'}};
T2 = T(2:3, :); n2 = height(T2); nm2 = T2.Name;
T3 = T(:, {'Name', 'Age'}); w3 = width(T3);
T4 = T(T.Age > 40, :); n4 = height(T4);
T.Weight = [176; 163; 131]; w5 = width(T);
T(1, :) = []; n6 = height(T); first = T.Name{1};
T.Age(2) = 50; ag = T.Age;
T(end+1, :) = {'Di', 29, false, 120}; n7 = height(T); last = T.Name{end};
T{1, 'Age'} = 44; ag2 = T.Age;
x = [1; 2; 3]; U = table(x); U.x(2) = 9; xs = x; ux = U.x;
V = table([1; 2], {'a'; 'b'}, 'VariableNames', {'n', 's'}, 'RowNames', {'r1', 'r2'});
vr = V{'r2', 'n'}; rn = V.Properties.RowNames;
V.Properties.VariableNames{2} = 'label'; vn2 = V.Properties.VariableNames;
E = table(); E.a = [1; 2]; E.b = {'p'; 'q'}; ne = height(E);
S = table('Size', [2 3], 'VariableTypes', {'double', 'string', 'logical'}); sk = class(S.Var2); sv = S.Var1;
c1 = class(T); i1 = istable(T); i2 = istimetable(T);
K = [T(1:2, :); T(1, :)]; nk = height(K);
H = [T(:, 'Name'), table([7; 8; 9], 'VariableNames', {'z'})]; wh = width(H);
D = T; D(:, 'Ok') = []; wd = width(D);
""")
same('variables named after the variables given', W['vn'], ['Name', 'Age', 'Ok'])
near('size, height, width', (W['sz'], W['h'], W['w']), [3, 3, 3, 3])
near('T.Age', W['a'], [38, 43, 38])
same('T{2, name}', W['b'], ['Bo'])
near('T{:, {name}}', W['c'], [38, 43, 38])
near('T(2:3, :) has two rows', W['n2'], 2)
same('... of the right names', W['nm2'], ['Bo', 'Cy'])
near('T(:, names)', W['w3'], 2)
near('T(mask, :)', W['n4'], 1)
near('T.New = ... adds a variable', W['w5'], 4)
near('T(1, :) = [] deletes the row', W['n6'], 2)
same('... the first row is now Bo', W['first'], 'Bo')
near('T.Age(2) = 50', W['ag'], [43, 50])
near('T(end+1, :) = {...} adds a row', W['n7'], 3)
same('... with its text', W['last'], 'Di')
near('T{1, name} = v', W['ag2'], [44, 50, 29])
near('a change through T.x(2) leaves the variable it came from alone', (W['xs'], W['ux']), [1, 2, 3, 1, 9, 3])
near('row names pick rows', W['vr'], 2)
same('... and are a property', W['rn'], ['r1', 'r2'])
same('T.Properties.VariableNames{2} = ... renames', W['vn2'], ['n', 'label'])
near('an empty table grows by adding variables', W['ne'], 2)
same("table('Size', ..., 'VariableTypes', ...)", W['sk'], 'string')
near('... numbers start as zeros', W['sv'], [0, 0])
C('class, istable, istimetable', text(W['c1']) == 'table' and W['i1'] is True and W['i2'] is False, (W['c1'], W['i1'], W['i2']))
near('[T1; T2] puts rows together', W['nk'], 3)
near('[T1, T2] puts variables together', W['wh'], 2)
near("T(:, 'x') = [] deletes a variable", W['wd'], 3)

for code, words in [("T = table([1; 2]); T(1)", 'two subscripts'),
                    ("T = table([1; 2]); T.nope", "'nope'"),
                    ("T = table([1; 2]); T(5, :)", 'exceeds'),
                    ("table([1; 2], [1; 2; 3])", 'same number of rows'),
                    ("T = table([1; 2]); T + 1", 'not supported'),
                    ("T = table([1; 2]); [T, T]", 'Duplicate'),
                    ("T = table([1; 2], [3; 4]); T.Properties.VariableNames = {'a'};", 'number of variable names')]:
    m = err_of(code)
    C(f'error: {code}', words in m, m)

# ---- table display ----------------------------------------------------------------------------------
_, o = run("T = table({'Ann'; 'Bo'}, [38; 4], [1.5; 2.25], [true; false], 'VariableNames', {'Name', 'Age', 'H', 'Ok'})")
lines = o.split('\n')
C('display: size and class', '  2×4 table' in lines, o)
C('display: names centred over their columns, underlined', '     Name      Age     H       Ok' in lines and '    _______    ___    ____    _____' in lines, o)
C('display: text padded inside the braces, numbers to the right, logical to the left',
  "    {'Ann'}    38      1.5    true" in lines and "    {'Bo' }     4     2.25    false" in lines, o)

# ---- table functions ---------------------------------------------------------------------------------
W, o = run("""g = {'a'; 'b'; 'a'; 'b'; 'a'}; x = [1; 2; 3; 4; 5]; y = [10; 20; 30; 40; NaN];
T = table(g, x, y);
s = sortrows(T, 'x', 'descend'); sx = s.x;
[s2, i2] = sortrows(T, {'g', 'x'}, {'ascend', 'descend'});
u = unique(table([1; 2; 1], {'a'; 'b'; 'a'})); nu = height(u);
vf = varfun(@mean, T, 'InputVariables', {'x', 'y'}); vfn = vf.Properties.VariableNames; vfx = vf.mean_x;
vg = varfun(@sum, T, 'GroupingVariables', 'g', 'InputVariables', 'x'); vgs = vg.sum_x; vgc = vg.GroupCount;
vu = varfun(@max, T, 'InputVariables', 'x', 'OutputFormat', 'uniform');
rf = rowfun(@(a, b) a + b, T, 'InputVariables', {'x', 'y'}, 'OutputVariableNames', 'z'); rz = rf.z;
gs = groupsummary(T, 'g', 'mean', 'y'); gsm = gs.mean_y;
g2 = groupsummary(T, 'g', {'min', 'max'}, 'x'); g2n = g2.Properties.VariableNames;
A = table({'k1'; 'k2'; 'k3'}, [1; 2; 3], 'VariableNames', {'key', 'va'});
B = table({'k3'; 'k1'; 'k4'}, [30; 10; 40], 'VariableNames', {'key', 'vb'});
ij = innerjoin(A, B); ijk = ij.key; ijb = ij.vb;
oj = outerjoin(A, B, 'MergeKeys', true); ojk = oj.key; oja = oj.va; ojb = oj.vb;
[ol, ia, ib] = outerjoin(A, B, 'Type', 'left');
jn = join(A, table({'k3'; 'k2'; 'k1'}, [9; 8; 7], 'VariableNames', {'key', 'vc'})); jc = jn.vc;
sj = join({'a', 'b'}, '-');
av = addvars(A, [5; 6; 7], 'Before', 'va', 'NewVariableNames', 'w'); avn = av.Properties.VariableNames;
rv = removevars(A, 'va'); rvn = rv.Properties.VariableNames;
mv = movevars(A, 'key', 'After', 'va'); mvn = mv.Properties.VariableNames;
rn = renamevars(A, 'va', 'value'); rnn = rn.Properties.VariableNames;
sp = splitvars(table([1 2; 3 4])); spn = sp.Properties.VariableNames;
mg = mergevars(table([1; 2], [3; 4], {'p'; 'q'}), [1 2]); mgv = mg.Var1;
r2 = rows2vars(table([1; 2], [3; 4], 'RowNames', {'r1', 'r2'})); r2n = r2.Properties.VariableNames; r2v = r2.r2;
cv = convertvars(A, 'key', 'categorical'); cvc = class(cv.key);
ta = table2array(B(:, 2)); tc = table2cell(A(1:2, :));
st = table2struct(A); stn = numel(st); stk = st(2).key;
s2t = struct2table(st); s2n = height(s2t);
c2t = cell2table({'a', 1; 'b', 2}, 'VariableNames', {'n', 'v'}); c2v = c2t.v; c2c = class(c2t.n);
a2t = array2table(magic(3)); a2n = a2t.Properties.VariableNames; a2v = a2t.Var2;
hd = head(array2table((1:12)')); nh = height(hd);
tl = tail((1:10)', 2);
[tf, loc] = ismember(A([3 1], :), A);
eq1 = isequal(A, A); eq2 = isequal(A, B);
nv = T(:, vartype('numeric')); nvn = nv.Properties.VariableNames;
""")
near("sortrows by a variable, 'descend'", W['sx'], [5, 4, 3, 2, 1])
near('sortrows by two variables, the second descending: the order', W['i2'], [5, 3, 1, 4, 2])
near('unique rows of a table', W['nu'], 2)
same('varfun names its results after the function', W['vfn'], ['mean_x', 'mean_y'])
near('... mean of x', W['vfx'], 3)
near('varfun by groups: sums', W['vgs'], [9, 6])
near('... GroupCount', W['vgc'], [3, 2])
near("varfun 'uniform'", W['vu'], 5)
near('rowfun', W['rz'], [11, 22, 33, 44, np.nan])
near('groupsummary leaves NaN out of the mean', W['gsm'], [20, 30])
same('groupsummary: GroupCount, then each method of the variable', W['g2n'], ['g', 'GroupCount', 'min_x', 'max_x'])
same('innerjoin: the keys in both, sorted', W['ijk'], ['k1', 'k3'])
near('... with their values', W['ijb'], [10, 30])
same('outerjoin with merged keys: every key', W['ojk'], ['k1', 'k2', 'k3', 'k4'])
near('... missing values where a table has no row', (W['oja'], W['ojb']), [1, 2, 3, np.nan, 10, np.nan, 30, 40])
near("outerjoin 'left': the rows of A, with B's matches (0 for none)", (W['ia'], W['ib']), [1, 2, 3, 2, 0, 1])
near('join matches each row of A to its key in B', W['jc'], [7, 8, 9])
same('join of text is still the text join', W['sj'], 'a-b')
same("addvars 'Before'", W['avn'], ['key', 'w', 'va'])
same('removevars', W['rvn'], ['key'])
same("movevars 'After'", W['mvn'], ['va', 'key'])
same('renamevars', W['rnn'], ['key', 'value'])
same('splitvars', W['spn'], ['Var1_1', 'Var1_2'])
near('mergevars', W['mgv'], [1, 2, 3, 4])
same('rows2vars: the names, then a variable per row', W['r2n'], ['OriginalVariableNames', 'r1', 'r2'])
near('... each holding its row', W['r2v'], [2, 4])
same('convertvars to categorical', W['cvc'], 'categorical')
near('table2array', W['ta'], [30, 10, 40])
C('table2cell: a cell per row and variable', isinstance(W['tc'], Cell) and W['tc'].a.shape == (2, 2) and text(W['tc'].a[1, 0]) == 'k2', W['tc'])
near('table2struct: an element per row', W['stn'], 3)
same('... its fields the variables', W['stk'], 'k2')
near('struct2table back', W['s2n'], 3)
near('cell2table: numbers become a numeric variable', W['c2v'], [1, 2])
same('... text stays a cell', W['c2c'], 'cell')
same('array2table: Var1, Var2, ...', W['a2n'], ['Var1', 'Var2', 'Var3'])
near('... the columns', W['a2v'], [1, 5, 9])
near('head: 8 rows', W['nh'], 8)
near('tail of an array', W['tl'], [9, 10])
near('ismember of table rows', (W['tf'], W['loc']), [1, 1, 3, 1])
C('isequal of tables', W['eq1'] is True and W['eq2'] is False, (W['eq1'], W['eq2']))
same("vartype('numeric') picks the numeric variables", W['nvn'], ['x', 'y'])

# ---- timetables --------------------------------------------------------------------------------------
W, o = run("""t = datetime(2026, 1, 1, [0; 1; 3; 4; 7], 0, 0);
TT = timetable(t, [1; 2; 3; 4; 5], {'a'; 'b'; 'c'; 'd'; 'e'}, 'VariableNames', {'x', 's'});
tn = TT.Properties.DimensionNames; c = class(TT); it = istimetable(TT);
r1 = TT(datetime(2026, 1, 1, 3, 0, 0), :); r1x = r1.x;
r2 = TT(timerange(datetime(2026,1,1,1,0,0), datetime(2026,1,1,4,0,0)), :); r2x = r2.x;
h1 = retime(TT, 'hourly'); n1 = height(h1); x1 = h1.x;
h2 = retime(TT(:, 'x'), 'hourly', 'linear'); x2 = h2.x;
h3 = retime(TT, 'hourly', 'previous'); s3 = h3.s;
h4 = retime(TT(:, 'x'), 'regular', 'mean', 'TimeStep', hours(3)); x4 = h4.x;
h5 = retime(TT(:, 'x'), 'daily', 'sum'); x5 = h5.x;
h6 = retime(TT(:, 'x'), 'hourly', 'fillwithconstant', 'Constant', -1); x6 = h6.x;
A = timetable(datetime(2026,1,1) + days([0; 1; 2]), [1; 2; 3], 'VariableNames', {'v'});
B = timetable(datetime(2026,1,1) + days([1; 3]), [10; 30], 'VariableNames', {'v'});
sy = synchronize(A, B); syn = sy.Properties.VariableNames; sya = sy.v_A; syb = sy.v_B;
si = synchronize(A, B, 'intersection'); nsi = height(si);
[g1, st1] = isregular(A); st1h = hours(st1); g2 = isregular(TT);
S = timetable([1; 2; 3], 'SampleRate', 10); ss = seconds(S.Time); sstep = char(S.Properties.TimeStep);
P = timetable([4; 5], 'TimeStep', minutes(15), 'StartTime', datetime(2026,5,1,8,0,0)); pl = char(P.Time(2));
pr = P.Properties.TimeStep; prm = minutes(pr); srate = P.Properties.SampleRate;
T2 = timetable2table(P); t2n = T2.Properties.VariableNames;
T3 = table2timetable(table(datetime(2026,1,1) + days([0; 1]), [3; 4], 'VariableNames', {'when', 'y'})); t3n = T3.Properties.DimensionNames; t3c = class(T3);
D = timetable(seconds([0; 1; 2]), [5; 6; 7]); dd = retime(D, 'regular', 'linear', 'TimeStep', seconds(0.5)); ddv = dd.Var1;
srt = sortrows(timetable(datetime(2026,1,[3; 1; 2]), [3; 1; 2])); sv = srt.Var1;
""")
same('a timetable: the first dimension is Time', W['tn'], ['Time', 'Variables'])
C('class, istimetable', text(W['c']) == 'timetable' and W['it'] is True, (W['c'], W['it']))
near('a row picked by its time', W['r1x'], 3)
near('timerange: from the start up to (not including) the end', W['r2x'], [2, 3])
near("retime 'hourly': eight hours", W['n1'], 8)
near('... missing values where no row was', W['x1'], [1, 2, np.nan, 3, 4, np.nan, np.nan, 5])
near("retime 'linear'", W['x2'], [1, 2, 2.5, 3, 4, 4 + 1 / 3, 4 + 2 / 3, 5], 1e-12)
same("retime 'previous' fills text too", W['s3'], ['a', 'b', 'b', 'c', 'd', 'd', 'd', 'e'])
near("retime 'mean' over steps of 3 hours", W['x4'], [1.5, 3.5, 5])
near("retime 'daily' 'sum': one day", W['x5'], 15)
near("'fillwithconstant'", W['x6'], [1, 2, -1, 3, 4, -1, -1, 5])
same('synchronize: names they share get the inputs\' names', W['syn'], ['v_A', 'v_B'])
near('... at the union of the times', (W['sya'], W['syb']), [1, 2, 3, np.nan, np.nan, 10, np.nan, 30])
near("synchronize 'intersection'", W['nsi'], 1)
C('isregular: a daily timetable', W['g1'] is True and abs(float(W['st1h']) - 24) < 1e-12, (W['g1'], W['st1h']))
C('isregular: an irregular one', W['g2'] is False, W['g2'])
near("'SampleRate' 10: times 0, 0.1, 0.2 s", W['ss'], [0, 0.1, 0.2], 1e-12)
same('... its TimeStep shown as the row times are', W['sstep'], '0.1 sec')
same("'TimeStep' and 'StartTime'", W['pl'], '01-May-2026 08:15:00')
near('Properties.TimeStep and SampleRate', (W['prm'], W['srate']), [15, 1 / 900], 1e-12)
same('timetable2table: the times become the first variable', W['t2n'], ['Time', 'Var1'])
same('table2timetable: a datetime variable becomes the row times', W['t3n'], ['when', 'Variables'])
same('... a timetable', W['t3c'], 'timetable')
near('retime of duration row times', W['ddv'], [5, 5.5, 6, 6.5, 7])
near('sortrows of a timetable sorts by time', W['sv'], [1, 2, 3])

# ---- files: writetable and readtable ----------------------------------------------------------------
W, o = run("""dts = datetime(2026,1,1) + days(0:2)';
W1 = table(dts, [1.5; 2.5; 3.5], categorical({'u'; 'v'; 'u'}), string({'p'; 'q'; 'r'}), 'VariableNames', {'when', 'val', 'grp', 'txt'});
writetable(W1, 'w.csv'); txt = fileread('w.csv');
R1 = readtable('w.csv'); rc = class(R1.when); rv = R1.val; rt = R1.txt; rn = R1.Properties.VariableNames;
writetable(W1, 'w.xlsx'); R2 = readtable('w.xlsx'); r2v = R2.val; r2c = class(R2.when);
R3 = readtable('w.csv', 'TextType', 'string'); r3c = class(R3.txt);
fid = fopen('h.txt', 'w'); fprintf(fid, 'first name\\tAge\\nAnn\\t3\\nBo\\t\\n'); fclose(fid);
R4 = readtable('h.txt'); r4n = R4.Properties.VariableNames; r4a = R4.Age;
R5 = readtable('h.txt', 'VariableNamingRule', 'preserve'); r5n = R5.Properties.VariableNames;
writetable(table([1; 2], 'RowNames', {'a', 'b'}), 'rn.csv', 'WriteRowNames', true); R6 = readtable('rn.csv', 'ReadRowNames', true); r6 = R6.Properties.RowNames;
""")
same('writetable: a header, then a line per row', text(W['txt']).replace('\r', ''), 'when,val,grp,txt\n01-Jan-2026,1.5,u,p\n02-Jan-2026,2.5,v,q\n03-Jan-2026,3.5,u,r\n')
same('readtable: dates read as datetimes', W['rc'], 'datetime')
near('... numbers as numbers', W['rv'], [1.5, 2.5, 3.5])
same('... text as a cell array', W['rt'], ['p', 'q', 'r'])
same('... the header names the variables', W['rn'], ['when', 'val', 'grp', 'txt'])
near('an .xlsx file written and read back', W['r2v'], [1.5, 2.5, 3.5])
same('... its dates too', W['r2c'], 'datetime')
same("'TextType', 'string'", W['r3c'], 'string')
same('names made valid: white space dropped, the next letter a capital', W['r4n'], ['firstName', 'Age'])
near('an empty cell of a number column is NaN', W['r4a'], [3, np.nan])
same("'VariableNamingRule', 'preserve'", W['r5n'], ['first name', 'Age'])
same('row names written and read back', W['r6'], ['a', 'b'])

W, o = run("""a = matlab.lang.makeValidName({'for', '1x', 'a$b', ' ok  go ', 'fine'});
[n, m] = matlab.lang.makeValidName({'a b', 'c'});
h = matlab.lang.makeValidName('a$b', 'ReplacementStyle', 'hex');
g = genvarname({'a', 'a', 'a'}); g2 = genvarname('x', {'x', 'x1'});""")
same('makeValidName: keywords, leading digits, other characters, white space', W['a'], ['xFor', 'x1x', 'a_b', 'okGo', 'fine'])
near('... which names it changed', W['m'], [1, 0])
same("'ReplacementStyle', 'hex'", W['h'], 'a0x24b')
same('genvarname makes the names unique', W['g'], ['a', 'a1', 'a2'])
same('... and unlike the exclusions', W['g2'], 'x2')

# ---- summary -----------------------------------------------------------------------------------------
_, o = run("""T = table([1; NaN; 3; 40], categorical({'u'; 'v'; 'u'; 'u'}), 'VariableNames', {'n', 'c'});
T.Properties.VariableUnits = {'m', ''}; summary(T)""")
C('summary: each variable, its units, min, median, max and missing; categories counted',
  'n: 4×1 double' in o and 'Units:  m' in o and 'Median         3' in o and 'NumMissing     1' in o and 'u    3' in o, o)

# ---- missing values ----------------------------------------------------------------------------------
W, o = run("""x = [1 missing 3]; s = ["a" missing]; sm = ismissing(s);
d = datetime(2026,1,1) + days(0:2); d(2) = missing; nd = isnat(d);
c = categorical({'x','y'}); c(3) = missing; uc = isundefined(c);
m = missing; mc = class(m); mi = ismissing(m); ms = string(missing); md = double(missing); ma = missing + 1;
dt = [datetime(2026,1,1) missing]; dtn = isnat(dt);
try, z = int8([1 2]); z(2) = missing; e = 'none'; catch err, e = err.message; end""")
near('[1 missing 3] is [1 NaN 3]', W['x'], [1, np.nan, 3])
near('in a string array, a missing string', W['sm'], [0, 1])
near('in a datetime, NaT', W['nd'], [0, 1, 0])
near('in a categorical, undefined', W['uc'], [0, 0, 1])
C('missing: its class, ismissing, string, double, arithmetic', text(W['mc']) == 'missing' and W['mi'] is True and W['ms'].a.flat[0] is None and np.isnan(W['md']) and np.isnan(W['ma']),
  (W['mc'], W['mi'], W['md'], W['ma']))
near('[datetime missing] ends in NaT', W['dtn'], [0, 1])
C('an integer array refuses missing', 'int8' in text(W['e']), W['e'])

W, o = run("""d = datetime(2026,1,1) + days(0:3); d([2 3]) = NaT;
f1 = fillmissing(d, 'previous'); f2 = fillmissing(d, 'linear'); f3 = fillmissing(d, 'constant', datetime(2000,1,1));
r = rmmissing(d); [r2, tf] = rmmissing(d);
c = categorical({'x','','y',''}); g1 = fillmissing(c, 'constant', 'z'); g2 = fillmissing(c, 'previous'); gc = categories(g1);
try, fillmissing(c, 'linear'); e = 'none'; catch err, e = err.message; end
du = hours([1 NaN 3]); h = hours(fillmissing(du, 'linear'));
sc = standardizeMissing(categorical({'a','na','b'}), 'na'); su = isundefined(sc);
sd = standardizeMissing(datetime(2026,1,1) + days(0:1), datetime(2026,1,2)); sn = isnat(sd);""")
near('fillmissing of datetimes: previous', v(W['f1'].a) / 86400, (np.array([0, 0, 0, 3]) + 20454))
near('... linear', v(W['f2'].a) / 86400, np.array([0, 1, 2, 3]) + 20454)
near('... a constant datetime', v(W['f3'].a) / 86400, [20454, 10957, 10957, 20457])
C('rmmissing of datetimes, and which were missing', W['r'].a.size == 2 and np.array_equal(np.asarray(W['tf']).reshape(-1), [0, 1, 1, 0]), (W['r'].a, W['tf']))
C("categorical: 'constant' adds the category; 'previous' copies", [text(x) for x in W['gc'].a.reshape(-1)] == ['x', 'y', 'z']
  and np.array_equal(np.asarray(W['g2'].a).reshape(-1), [1, 1, 2, 2]), (W['gc'], W['g2'].a))
C("... 'linear' is refused for categories", 'categorical' in text(W['e']), W['e'])
near('durations fill linearly', W['h'], [1, 2, 3])
near('standardizeMissing: a category name made undefined', W['su'], [0, 1, 0])
near('... a datetime made NaT', W['sn'], [0, 1])

W, o = run("""T = table([1;NaN;3], {'a';'';'c'}, categorical({'x';'';'y'}), datetime(2026,1,1)+days([0;NaN;2]), 'VariableNames', {'n','s','c','d'});
M = ismissing(T); R1 = rmmissing(T); h1 = height(R1);
[F, tf] = fillmissing(T, 'previous'); fn = F.n; fs = F.s; ftf = tf;
G = fillmissing(T, 'constant', {0, 'none', 'x', datetime(2000,1,1)}); gn = G.n; gs = G.s{2};
L = fillmissing(T, 'linear', 'DataVariables', 'n'); ln = L.n; ls = L.s{2};
R2 = rmmissing(T, 'DataVariables', 'n'); h2 = height(R2);
S = standardizeMissing(table([1;-99;3], {'a';'-99';'b'}), -99); sn = S.Var1; ss = S.Var2{2};""")
C('ismissing of a table: each variable side by side', np.array_equal(np.asarray(W['M']).astype(int), [[0, 0, 0, 0], [1, 1, 1, 1], [0, 0, 0, 0]]), W['M'])
C('rmmissing of a table drops the rows with a missing element', W['h1'] == 2 and W['h2'] == 2, (W['h1'], W['h2']))
near("fillmissing of a table, 'previous', each variable", W['fn'], [1, 1, 3])
C('... text too, and which were filled', text(W['fs']) == ['a', 'a', 'c'] and np.asarray(W['ftf']).astype(int).tolist()[1] == [1, 1, 1, 1], (W['fs'], W['ftf']))
C("'constant' with one value per variable", np.allclose(v(W['gn']), [1, 0, 3]) and text(W['gs']) == 'none', (W['gn'], W['gs']))
C("'DataVariables' fills only those", np.allclose(v(W['ln']), [1, 2, 3]) and text(W['ls']) == '', (W['ln'], W['ls']))
C('standardizeMissing of a table: a number indicator in the number variable only', np.isnan(v(W['sn'])[1]) and text(W['ss']) == '-99', (W['sn'], W['ss']))

# ---- categorical data in plots --------------------------------------------------------------------------
W, o = run("""f = figure('Visible', 'off'); c = categorical({'apple','pear','apple','fig','apple','pear'});
h = histogram(c); y = get(h, 'YData'); kx = gca; k = kx.XLim;
h2 = histogram(c, 'Normalization', 'probability'); p = get(h2, 'YData');
b = bar(categorical({'lo','mid','hi'}, {'lo','mid','hi'}), [3 5 2]); bx = get(b, 'XData'); bxl = xlim;
pl = plot(categorical({'a','b','c'}), [1 4 2], '-o'); px = get(pl, 'XData');""")
near('histogram of a categorical: the count of each category, in their order', W['y'], [3, 1, 2])
near("... 'probability'", W['p'], [0.5, 1 / 6, 1 / 3])
near('bar of categories: each at its place', (W['bx'], W['bxl']), [1, 2, 3, 0.5, 3.5])
near('plot of categories', W['px'], [1, 2, 3])
from plab.graphics_base import STORE as _STORE  # noqa: E402
kinds = [getattr(a, 'kinds', None) for a in list(_STORE.objects.values()) if getattr(a, 'kinds', None)]
C('the axis knows it holds categories, and their names', any(str(k.get('x', '')).startswith('categorical:["a", "b", "c"]') for k in kinds), kinds[-3:])
run('close all')

# ---- the Variable editor ------------------------------------------------------------------------------
from plab import worker_api as WA  # noqa: E402
_dbg = R.DEBUGGER
R.DEBUGGER = WA.Debugger()
try:
    run("T = table([1;2], {'a';'b'}, [1 2; 3 4], 'RowNames', {'r1','r2'}); TT = timetable(seconds([0;1]), [5;6]); d = datetime(2026,1,1) + days([0 1; 2 3]); c = categorical({'x','y',''});")
    vt, vtt, vd, vc = (json.loads(WA.var_view(n)) for n in ('T', 'TT', 'd', 'c'))
    C('Variable editor: a table as its variables over its rows, the row names beside',
      vt['kind'] == 'table' and vt['fields'] == ['Var1', 'Var2', 'Var3'] and vt['rowLabels'] == ['r1', 'r2'] and vt['cells'][1] == ['2', "{'b'}", '3    4'], vt)
    C('... a timetable with its row times', vtt['kind'] == 'table' and vtt['rowHead'] == 'Time' and vtt['rowLabels'] == ['0 sec', '1 sec'] and vtt['cells'] == [['5'], ['6']], vtt)
    C('... datetimes and categoricals as their elements display', vd['kind'] == 'grid' and vd['cells'][1] == ['03-Jan-2026', '04-Jan-2026'] and vc['cells'] == [['x', 'y', '<undefined>']], (vd, vc))
finally:
    R.DEBUGGER = _dbg

sys.exit(C.done())
