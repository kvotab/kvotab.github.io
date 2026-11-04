"""The language's smaller pieces, run natively: meta.class objects (?Name,
metaclass, their property, method, event, enumeration and superclass lists,
subclass comparisons), obj.method called without parentheses, dot calls on
graphs, subsref, subsasgn and substruct, namedargs2cell, isStringScalar,
base64 against Python's base64, unicode2native and native2unicode against
Python's codecs, textwrap, the release checks, calendar against Python's
calendar, array2timetable, fileattrib and recycle, and the reductions'
'omitmissing' and 'includemissing'.

    python3 test_langmore.py          (from any folder)
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
TMP = tempfile.mkdtemp(prefix='pylab-langmore-')
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



def text(v):
    from plab.values import py_str
    return py_str(v)


def flat(x):
    return np.asarray(x, dtype=float).reshape(-1).tolist()


def write(name, src):
    with open(os.path.join(TMP, name), 'w') as f:
        f.write(src)


write('Acct.m', """classdef Acct < handle
    properties
        Balance = 0
    end
    properties (SetAccess = private)
        Owner = 'nobody'
    end
    properties (Dependent)
        Doubled
    end
    events
        Changed
    end
    methods
        function obj = Acct(b)
            if nargin, obj.Balance = b; end
        end
        function deposit(obj, amount)
            obj.Balance = obj.Balance + amount;
        end
        function v = get.Doubled(obj)
            v = 2*obj.Balance;
        end
        function v = twice(obj)
            v = 2*obj.Balance;
        end
    end
    methods (Static)
        function r = rate()
            r = 0.02;
        end
    end
end
""")
write('Savings.m', """classdef Savings < Acct
    properties
        Rate = 0.03
    end
    methods
        function addInterest(obj)
            obj.Balance = obj.Balance*(1 + obj.Rate);
        end
    end
end
""")
write('Shade.m', """classdef Shade
    enumeration
        Light, Dark
    end
end
""")

# ---- meta.class ------------------------------------------------------------------------------------------------
W, _ = run("""mc = ?Acct; cls = class(mc); nm = mc.Name; hc = mc.HandleCompatible; pn = {mc.PropertyList.Name};
sa = mc.PropertyList(2).SetAccess; dep = mc.PropertyList(3).Dependent; dv = mc.PropertyList(1).DefaultValue;
mn = {mc.MethodList.Name}; st = findobj(mc.MethodList, 'Name', 'rate'); stat = st.Static; ev = mc.EventList(1).Name;
s = ?Savings; spn = {s.PropertyList.Name}; sup = s.SuperclassList(1).Name; def1 = s.PropertyList(2).DefiningClass.Name;
lt = s < ?Acct; gt = ?Acct < ?Savings; eqs = s == ?Savings; le = s <= ?Savings;
e = ?Shade; en = {e.EnumerationMemberList.Name}; isen = e.Enumeration;
d = ?double; dn = d.Name; dsz = size(d.PropertyList); z = ?NoSuchClassHere; zs = size(z); zc = class(z);
a = Acct(5); m2 = metaclass(a); same = m2 == ?Acct; m3 = metaclass(3).Name; fn = meta.class.fromName('Savings').Name;""")
same('?Acct is a meta.class with its name and handle compatibility', (text(W['cls']), text(W['nm']), bool(W['hc'])), ('meta.class', 'Acct', True))
same('PropertyList: the properties in order with their access, Dependent and defaults',
     ([text(x) for x in W['pn'].a.reshape(-1)], text(W['sa']), bool(W['dep']), float(W['dv'])), (['Balance', 'Owner', 'Doubled'], 'private', True, 0.0))
mn = [text(x) for x in W['mn'].a.reshape(-1)]
same("MethodList: the constructor, the methods (a static one Static), then handle's", (mn[:4], 'addlistener' in mn, 'delete' in mn, bool(W['stat']), text(W['ev'])),
     (['Acct', 'deposit', 'twice', 'rate'], True, True, True, 'Changed'))
same('a subclass lists its own and inherited properties, its superclass, and where each is defined',
     ([text(x) for x in W['spn'].a.reshape(-1)], text(W['sup']), text(W['def1'])), (['Rate', 'Balance', 'Owner', 'Doubled'], 'Acct', 'Acct'))
same('meta.class < means derives from; == the same class', (bool(W['lt']), bool(W['gt']), bool(W['eqs']), bool(W['le'])), (True, False, True, True))
same('an enumeration lists its members', ([text(x) for x in W['en'].a.reshape(-1)], bool(W['isen'])), (['Light', 'Dark'], True))
same('?double has empty lists; an unknown class gives an empty meta.class array',
     (text(W['dn']), flat(W['dsz']), flat(W['zs']), text(W['zc'])), ('double', [0.0, 1.0], [0.0, 0.0], 'meta.class'))
same('metaclass of an object and of a number; meta.class.fromName', (bool(W['same']), text(W['m3']), text(W['fn'])), (True, 'double', 'Savings'))

# ---- obj.method without parentheses; dot calls on graphs ----------------------------------------------------------
W, _ = run("a = Acct(4); t = a.twice; r = a.rate; a.deposit(1); b = a.Balance; G = graph([1 2], [2 3]); nn = G.numnodes; sp = G.shortestpath(1, 3);")
same('obj.method without parentheses calls it; a static one through an object too', (float(W['t']), float(W['r']), float(W['b'])), (8.0, 0.02, 5.0))
same("a graph's functions called with a dot", (float(W['nn']), flat(W['sp'])), (3.0, [1.0, 2.0, 3.0]))
W, _ = run("f = figure('Visible', 'off'); u = uicontrol('Callback', @(s, e) 1); cb = class(u.Callback); close(f); s.fn = @sin; g = class(s.fn);")
same('a callback kept in a property stays a function handle', (text(W['cb']), text(W['g'])), ('function_handle', 'function_handle'))

# ---- subsref, subsasgn, substruct --------------------------------------------------------------------------------------
W, _ = run("""S = substruct('()', {2}, '.', 'f'); q = struct('f', {10, 20}); r1 = subsref(q, S);
C = {1, [5 6 7]}; r2 = subsref(C, substruct('{}', {2}, '()', {3})); q2 = subsasgn(q, S, 99); r3 = [q2.f]; r3b = [q.f];
B = subsasgn(magic(3), substruct('()', {':', 1}), [0; 0; 0]); r4 = B(:, 1)'; r5 = subsref(magic(4), substruct('()', {2, ':'}));
[u, v] = subsref({1, 2}, substruct('{}', {':'})); st = size(S); ty = S(1).type;""")
same('subsref: A(2).f, C{2}(3), a row with a colon, two outputs from a brace',
     (float(W['r1']), float(W['r2']), flat(W['r5']), (float(W['u']), float(W['v']))), (20.0, 7.0, [5.0, 11.0, 10.0, 8.0], (1.0, 2.0)))
same('subsasgn changes the copy only, also through a colon', (flat(W['r3']), flat(W['r3b']), flat(W['r4'])),
     ([10.0, 99.0], [10.0, 20.0], [0.0, 0.0, 0.0]))
same('substruct: a 1-by-n struct of type and subs', (flat(W['st']), text(W['ty'])), ([1.0, 2.0], '()'))
raises("substruct('[]', {1})", "Each type is '()', '{}' or '.'")
raises("subsref(1, struct('type', '()'))", 'struct array with the fields type and subs')

# ---- small conversions ------------------------------------------------------------------------------------------------
import base64 as _b64  # noqa: E402
W, _ = run("""c = namedargs2cell(struct('a', 1, 'b', 'x')); c1 = c{1}; c3 = c{3}; nc = numel(c);
i1 = isStringScalar("a"); i2 = isStringScalar(["a" "b"]); i3 = isStringScalar('a');
b = matlab.net.base64encode(uint8('hello world!')); bs = matlab.net.base64encode("åäö"); bc = class(bs); back = char(matlab.net.base64decode(b));
bb = matlab.net.base64decode('aGk'); n1 = unicode2native('åb', 'ISO-8859-1'); n2 = unicode2native('å'); n3 = native2unicode(uint8([195 165 98]));
n4 = native2unicode(uint8([229 98]), 'latin1');""")
same('namedargs2cell: name, value, name, value', (text(W['c1']), text(W['c3']), float(W['nc'])), ('a', 'b', 4.0))
same('isStringScalar', (bool(W['i1']), bool(W['i2']), bool(W['i3'])), (True, False, False))
same("base64 as Python's base64; a string stays a string; padding added when missing",
     (text(W['b']), text(W['bs']), text(W['bc']), text(W['back']), flat(W['bb'])),
     (_b64.b64encode(b'hello world!').decode(), _b64.b64encode('åäö'.encode()).decode(), 'string', 'hello world!', [104.0, 105.0]))
same("unicode2native and native2unicode as Python's codecs", (flat(W['n1']), flat(W['n2']), text(W['n3']), text(W['n4'])),
     ([float(x) for x in 'åb'.encode('latin-1')], [float(x) for x in 'å'.encode()], 'åb', 'åb'))
W, _ = run("w = textwrap({'The quick brown fox jumps over the lazy dog'}, 10); n = numel(w); w1 = w{1}; w3 = w{3}; mx = max(cellfun(@numel, w));")
same('textwrap: words kept whole, lines no wider than asked', (float(W['n']), text(W['w1']), text(W['w3']), float(W['mx']) <= 10), (5.0, 'The quick', 'jumps over', True))
W, _ = run("r1 = isMATLABReleaseOlderThan('R2020a'); r2 = verLessThan('matlab', '9.4');")
same('the release checks say no older', (bool(W['r1']), bool(W['r2'])), (False, False))
raises("isMATLABReleaseOlderThan('2020a')", "like 'R2024b'")

# ---- calendar, array2timetable ---------------------------------------------------------------------------------------
import calendar as _cal  # noqa: E402
W, out = run("c = calendar(2024, 2); calendar(2023, 12)")
want = np.zeros((6, 7))
for i, week in enumerate(_cal.Calendar(firstweekday=6).monthdayscalendar(2024, 2)):
    want[i] = week
near("calendar: February 2024 from Sunday, as Python's calendar", W['c'], want)
C('calendar with no output prints the month', 'Dec 2023' in out and '31' in out, out[:120])
W, _ = run("tt = array2timetable([1 2; 3 4; 5 6], 'RowTimes', seconds(1:3)); vn = tt.Properties.VariableNames; v2 = tt.Var2'; t2 = array2timetable(magic(3), 'SampleRate', 2, 'VariableNames', {'a','b','c'}); h = height(t2); n2 = t2.Properties.VariableNames;")
same('array2timetable: a variable for each column, named Var1... or as given', ([text(x) for x in W['vn'].a.reshape(-1)], flat(W['v2']), float(W['h']),
     [text(x) for x in W['n2'].a.reshape(-1)]), (['Var1', 'Var2'], [2.0, 4.0, 6.0], 3.0, ['a', 'b', 'c']))

# ---- fileattrib, recycle ------------------------------------------------------------------------------------------------
W, out = run("""fid = fopen('fa.txt', 'w'); fprintf(fid, 'x'); fclose(fid);
[st, v] = fileattrib('fa.txt'); ur = v.UserRead; d = v.directory; ar = v.archive;
fileattrib('fa.txt', '-w'); [~, v2] = fileattrib('fa.txt'); w2 = v2.UserWrite; fileattrib('fa.txt', '+w', 'u'); [~, v3] = fileattrib('fa.txt'); w3 = v3.UserWrite;
[s4, m4, id4] = fileattrib('nothing-here.txt'); r0 = recycle; recycle on; r1 = recycle; recycle('off');""")
import stat as _stat  # noqa: E402
mode = os.stat(os.path.join(TMP, 'fa.txt')).st_mode
same("fileattrib: the attributes as os.stat gives them; '-w' and '+w' change them", (bool(W['st']), bool(W['ur']), bool(W['d']), bool(np.isnan(W['ar'])),
     bool(W['w2']), bool(W['w3']), bool(mode & _stat.S_IWUSR)), (True, True, False, True, False, True, True))
same('fileattrib of nothing: status false, a message and an identifier', (bool(W['s4']), text(W['m4']), text(W['id4'])),
     (False, 'No such file or directory.', 'MATLAB:FILEATTRIB:CannotFindFile'))
same('recycle keeps its state', (text(W['r0']), text(W['r1'])), ('off', 'on'))

# ---- the newer names of the NaN flags ----------------------------------------------------------------------------------
W, _ = run("m = [mean([1 NaN 3], 'omitmissing') sum([1 NaN 3], 'omitmissing') median([1 NaN 3 5], 'omitmissing') max([1 NaN 3], [], 'includemissing') std([1 NaN 3], 'omitmissing')]; c = cumsum([1 NaN 3], 'omitmissing'); mf = medfilt1([1 NaN 3 4], 3, 'omitmissing');")
near("'omitmissing' and 'includemissing' as 'omitnan' and 'includenan'", (W['m'], W['c']), ([2.0, 4.0, 3.0, np.nan, math.sqrt(2.0)], [1.0, 1.0, 4.0]))
C("medfilt1 takes 'omitmissing' too", not np.any(np.isnan(a(W['mf']))), flat(W['mf']))

sys.exit(C.done())
