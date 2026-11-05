"""Unit tests: test classes (classdef ... < matlab.unittest.TestCase, with
Test, TestMethodSetup, TestMethodTeardown, TestClassSetup and
TestClassTeardown methods and TestParameter properties), function-based
tests (functiontests(localfunctions), with setupOnce, teardownOnce, setup
and teardown) and script-based tests (a script's %% sections, the code
before the first one shared); runtests, testsuite, run, TestRunner; the
qualifications (verify..., assert..., fatalAssert..., assume...);
TestResult and its table; matlab.unittest.TestCase.forInteractiveUse.

A verification that fails is recorded and the test goes on; an assertion
ends the test (failed); an assumption ends it as incomplete; a fatal
assertion ends the test and leaves the rest of the run undone."""
import fnmatch
import itertools
import os
import re
import time

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, num, is_str, darr
from ..values import MError, Obj, FH, Char, Cell, Struct, Str, Sparse, numel, py_str, text_list, class_of, shape_of
from .. import runtime as R
from .. import classdef as CD

TC_BASE = 'matlab.unittest.TestCase'
RULE = '=' * 80


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        return _register(*names, **kw)(f)
    return deco


# ---- test cases and what a run records ----------------------------------------------------------------------------------------------

class Record:
    """One test as it runs: its failures (diagnostic texts), whether it ended early and how, its time."""

    def __init__(self, name):
        self.name = name
        self.failures = []
        self.reasons = []            # 'verification', 'assertion', 'fatal assertion', 'error'
        self.incomplete = False
        self.assumed = False
        self.duration = 0.0
        self.teardowns = []

    @property
    def failed(self):
        return bool(self.failures)

    @property
    def passed(self):
        return not self.failures and not self.incomplete


RUN = {'records': [], 'detail': 2}


class Abort(Exception):
    """An assertion, fatal assertion or assumption that failed: the test ends."""

    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind


class FunctionTestCase(Obj):
    """The test case a function-based test (and its fixtures) is given: TestData is shared from setupOnce on."""
    cls = 'matlab.unittest.FunctionTestCase'
    is_handle = True

    def __init__(self, data=None, interactive=False):
        self.data = data if data is not None else Struct.scalar({})
        self.interactive = interactive

    def getprop(self, name):
        if name == 'TestData' and not self.interactive:
            return self.data
        if name in QUAL_NAMES or name in ('log', 'addTeardown'):
            return CD.BoundBuiltin(self, name)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{self.cls}'.")

    def setprop(self, name, value):
        if name == 'TestData' and not self.interactive:
            self.data = value
            return
        raise MError('MATLAB:noPublicFieldForClass', f"Unrecognized property '{name}' for class '{self.cls}'.")

    def propnames(self):
        return [] if self.interactive else ['TestData']

    def display_lines(self):
        if self.interactive:
            return ['  TestCase for interactive use: its qualifications print whether they passed.']
        from ..display import summary
        return [f'  {self.cls.split(".")[-1]} with properties:', '', f'    TestData: {summary(self.data)}']


class InteractiveTestCase(FunctionTestCase):
    cls = TC_BASE

    def __init__(self):
        super().__init__(interactive=True)


def _is_tc(v):
    if isinstance(v, FunctionTestCase):
        return True
    return isinstance(v, CD.UObj) and TC_BASE in v.ci.all_names()


def _tc(v, fn):
    if not _is_tc(v):
        raise err(f'MATLAB:unittest:{fn}:testCase', f'{fn} is a method of a test case: its first input is the test case (testCase.{fn}(...)).', fn)
    return v


# ---- showing values in diagnostics -------------------------------------------------------------------------------------------------------

def _show(v):
    from ..display import summary
    try:
        if isinstance(v, Str) and v.a.size <= 10:
            items = ['<missing>' if x is None else f'"{x}"' for x in v.a.reshape(-1, order='F')]
            return items[0] if len(items) == 1 else '[' + ' '.join(items) + ']'
        if isinstance(v, Char) and v.a.shape[0] <= 1:
            return "'" + v.str() + "'"
        if type(v) in (float, bool, complex) or (type(v) is np.ndarray and v.ndim == 2 and v.size <= 30):
            r = REG['mat2str'].fn(1, v, 6)
            s = py_str(r)
            c = class_of(v)
            return s if c in ('double', 'logical') else f'{c}({s})' if v.size == 1 else f'{c}({s})'
    except MError:
        pass
    return summary(v)


def _size(sh):
    return '×'.join(str(int(d)) for d in sh)


# ---- comparing -------------------------------------------------------------------------------------------------------------------------------

async def _compare(a, e, abst, relt, where=''):
    """None when actual a equals expected e (class, size and values; NaN equal to NaN; within a tolerance when one is
    given), else why not."""
    at = f' at {where}' if where else ''
    ca, ce = class_of(a), class_of(e)
    if ca != ce:
        return f'the classes differ{at}: {ca} (actual) and {ce} (expected)'
    sa, se = tuple(shape_of(a)), tuple(shape_of(e))
    if sa != se:
        return f'the sizes differ{at}: {_size(sa)} (actual) and {_size(se)} (expected)'
    if isinstance(a, Sparse):
        a, e = a.m.toarray(), e.m.toarray()
    if isinstance(a, Char):
        if not np.array_equal(a.a, e.a):
            return f'the text differs{at}'
        return None
    if type(a) in (float, bool, complex, int, np.ndarray):
        A, E = np.asarray(a), np.asarray(e)
        if A.dtype.kind in 'biufc':
            Af = A.astype(complex if A.dtype.kind == 'c' or E.dtype.kind == 'c' else float)
            Ef = E.astype(Af.dtype)
            same = (Af == Ef) | (np.isnan(Af) & np.isnan(Ef))
            if abst is not None or relt is not None:
                d = np.abs(Af - Ef)
                ok = np.zeros(d.shape, bool)
                if abst is not None:
                    ok |= d <= abst
                if relt is not None:
                    ok |= d <= relt * np.abs(Ef)
                same = same | ok
            if not np.all(same):
                bad = np.flatnonzero(~same.reshape(-1, order='F'))
                d = np.abs(Af - Ef).reshape(-1, order='F')[bad]
                tol = '' if abst is None and relt is None else ' (beyond the tolerance)'
                return (f'the values differ{at}{tol}: {bad.size} of {same.size} element{"s" if same.size != 1 else ""}, the first at index {bad[0] + 1}, '
                        f'the largest difference {np.nanmax(d) if np.any(np.isfinite(d)) else d[0]:g}')
            return None
    if isinstance(a, Str):
        xa, xe = a.a.reshape(-1, order='F'), e.a.reshape(-1, order='F')
        for i, (x, y) in enumerate(zip(xa, xe)):
            if x != y:
                return f'the strings differ{at}, first at element {i + 1}'
        return None
    if isinstance(a, Cell):
        for i, (x, y) in enumerate(zip(a.a.reshape(-1, order='F'), e.a.reshape(-1, order='F'))):
            r = await _compare(x, y, abst, relt, f'{where}{{{i + 1}}}')
            if r:
                return r
        return None
    if isinstance(a, Struct):
        if set(a.keys) != set(e.keys):
            return f'the fields differ{at}: {", ".join(sorted(set(a.keys) ^ set(e.keys)))}'
        for i in range(a.size):
            ea, ee = a.elem(i), e.elem(i)
            for k in a.keys:
                r = await _compare(ea[k], ee[k], abst, relt, f'{where}{f"({i + 1})" if a.size > 1 else ""}.{k}')
                if r:
                    return r
        return None
    if isinstance(a, FH) and not isinstance(a, Obj):
        return None if a.text() == e.text() else f'the function handles differ{at}'
    same = await R.call(None, 'isequaln', 1, (a, e))
    return None if bool(np.all(same)) else f'the values differ{at}'


# ---- qualifying ------------------------------------------------------------------------------------------------------------------------------

KINDS = {'verify': 'Verification', 'assert': 'Assertion', 'fatalAssert': 'Fatal assertion', 'assume': 'Assumption'}


def _qualified(kind, tc, ok, what, reason, lines, diag):
    """A qualification's outcome: recorded (and shown) in a run, shown for interactive use; an assertion,
    fatal assertion or assumption that failed ends the test."""
    word = KINDS[kind]
    interactive = isinstance(tc, InteractiveTestCase) or not RUN['records']
    if ok:
        if interactive:
            R.write(f'{word} passed.\n')
        return
    body = []
    if diag:
        body += ['    ' + ln for ln in diag.split('\n')]
    body.append(f'    {kind}{what} failed.')
    if reason:
        body.append(f'    --> {reason[0].upper()}{reason[1:]}.')
    body += ['    ' + ln for ln in lines]
    if interactive:
        R.write(f'{word} failed.\n' + '\n'.join(body) + '\n')
        if kind != 'verify':
            raise MError(f'MATLAB:unittest:{word.replace(" ", "")}', f'{word} failed: {kind}{what}' + (f': {reason}' if reason else '') + '.')
        return
    rec = RUN['records'][-1]
    text = f'{word} failed in {rec.name}.\n' + '\n'.join(body)
    if kind == 'assume':
        rec.incomplete = True
        rec.assumed = True
        rec.reasons.append('assumption')
        rec.failures_assumed = text
    else:
        rec.failures.append(text)
        rec.reasons.append(word.lower())
        if RUN['detail'] >= 1:
            R.write(f'\n{RULE}\n{text}\n{RULE}\n')
    if kind != 'verify':
        raise Abort(kind)


def _diag(v):
    if v is None:
        return ''
    if isinstance(v, FH):
        r = v.scall(1)
        return py_str(r) if is_str(r) else ''
    if is_str(v):
        return py_str(v)
    if isinstance(v, (Cell,)):
        return '\n'.join(str(x) for x in text_list(v))
    return ''


async def _call_fh(fh, nargout, fn):
    if not isinstance(fh, FH):
        raise err(f'MATLAB:unittest:{fn}:handle', f'{fn} takes a function handle to call.', fn)
    return await fh.acall(nargout, )


def _text(v):
    return py_str(v) if isinstance(v, (Char, Str)) and numel(v) >= 0 and (isinstance(v, Char) or v.a.size == 1) else None


def _make(kind, check):
    name = kind + check
    nreq = REQ[check]

    async def q(nargout, *args):
        if args:
            _tc(args[0], name)
        if len(args) < nreq + 1:
            raise MError('MATLAB:minrhs', 'Not enough input arguments.')
        tc = args[0]
        a = list(args[1:1 + nreq])
        rest = list(args[1 + nreq:])
        abst = relt = None
        if check in ('Equal', 'NotEqual'):
            while len(rest) >= 2 and is_str(rest[0]) and py_str(rest[0]).lower() in ('abstol', 'reltol'):
                k = py_str(rest.pop(0)).lower()
                t = float(np.max(np.abs(np.asarray(darr(rest.pop(0)), float))))
                if k == 'abstol':
                    abst = t
                else:
                    relt = t
        if len(rest) > 1:
            raise MError('MATLAB:TooManyInputs', 'Too many input arguments.')
        diag = _diag(rest[0]) if rest else ''
        ok, reason, lines, result = True, '', [], None
        if check in ('Equal', 'NotEqual'):
            why = await _compare(a[0], a[1], abst, relt)
            ok = why is None if check == 'Equal' else why is not None
            reason = why or '' if check == 'Equal' else 'the values are equal'
            lines = ['Actual:', '    ' + _show(a[0]), ('Expected:' if check == 'Equal' else 'Not expected:'), '    ' + _show(a[1])]
            if abst is not None or relt is not None:
                lines.append('Tolerance: ' + ', '.join(x for x in (f'absolute {abst:g}' if abst is not None else '', f'relative {relt:g}' if relt is not None else '') if x))
        elif check in ('True', 'False'):
            v = a[0]
            want = check == 'True'
            ok = class_of(v) == 'logical' and numel(v) == 1 and bool(np.all(v)) == want
            reason = '' if ok else ('the value is not a logical scalar' if class_of(v) != 'logical' or numel(v) != 1 else f'the value is {"false" if want else "true"}')
            lines = ['Actual:', '    ' + _show(v)]
        elif check in ('Error', 'Warning', 'WarningFree'):
            want = py_str(a[1]) if check != 'WarningFree' and is_str(a[1]) else None
            if check == 'Error':
                try:
                    await _call_fh(a[0], 0, name)
                    ok, reason = False, 'the function threw no error'
                except MError as e:
                    got = e.identifier or ''
                    ok = want is None or got == want
                    reason = '' if ok else f"the error thrown has the identifier '{got}'"
                    lines = [f"Error thrown: {got or '(no identifier)'}: {e.message if hasattr(e, 'message') else e}"]
                lines.append(f"Expected identifier: '{want}'")
            else:
                R.WARN_CAPTURE.append([])
                try:
                    result = await _call_fh(a[0], nargout, name)
                finally:
                    caught = R.WARN_CAPTURE.pop()
                ids = [i for i, _ in caught]
                if check == 'WarningFree':
                    ok = not caught
                    reason = '' if ok else f'the function issued {len(caught)} warning{"s" if len(caught) != 1 else ""}'
                    lines = [f"Warning: {i or '(no identifier)'}: {m}" for i, m in caught]
                else:
                    ok = want in ids
                    reason = '' if ok else ('the function issued no warning' if not caught else f"no warning has the identifier '{want}'")
                    lines = [f"Warning issued: {i or '(no identifier)'}: {m}" for i, m in caught] + [f"Expected identifier: '{want}'"]
        elif check in ('Empty', 'NotEmpty'):
            ok = (numel(a[0]) == 0) == (check == 'Empty')
            reason = '' if ok else f'the value is {"not " if check == "Empty" else ""}empty (its size {_size(shape_of(a[0]))})'
        elif check == 'Size':
            want = tuple(int(x) for x in np.asarray(darr(a[1])).reshape(-1))
            got = tuple(shape_of(a[0]))
            ok = got == want
            reason = '' if ok else f'the size is {_size(got)}, not {_size(want)}'
        elif check in ('Length', 'NumElements'):
            sh = shape_of(a[0])
            got = numel(a[0]) if check == 'NumElements' else (0 if min(sh) == 0 else max(sh))
            want = int(num(a[1]))
            ok = got == want
            reason = '' if ok else f'the {"number of elements" if check == "NumElements" else "length"} is {got}, not {want}'
        elif check in ('Class', 'InstanceOf'):
            cname = py_str(a[1])
            ok = class_of(a[0]) == cname if check == 'Class' else bool(await R.call(None, 'isa', 1, (a[0], Char.of(cname))))
            reason = '' if ok else f"the value's class is {class_of(a[0])}" + ('' if check == 'Class' else f', not {cname} or one of its subclasses')
        elif check in ('GreaterThan', 'GreaterThanOrEqual', 'LessThan', 'LessThanOrEqual'):
            A = np.asarray(darr(a[0]), float)
            B = np.asarray(darr(a[1]), float)
            op = {'GreaterThan': np.greater, 'GreaterThanOrEqual': np.greater_equal, 'LessThan': np.less, 'LessThanOrEqual': np.less_equal}[check]
            good = op(A, B)
            ok = bool(np.all(good)) and A.size > 0
            word = {'GreaterThan': 'greater than', 'GreaterThanOrEqual': 'at least', 'LessThan': 'less than', 'LessThanOrEqual': 'at most'}[check]
            reason = '' if ok else f'not every value is {word} {_show(a[1])}'
            lines = ['Actual:', '    ' + _show(a[0])]
        elif check == 'ReturnsTrue':
            r = await _call_fh(a[0], 1, name)
            ok = class_of(r) == 'logical' and numel(r) == 1 and bool(np.all(r))
            reason = '' if ok else f'the function gave {_show(r)}'
        elif check in ('Substring', 'Matches'):
            s, p = _text(a[0]), _text(a[1])
            if s is None or p is None:
                raise err(f'MATLAB:unittest:{name}:text', f'{name} compares text with text.', name)
            ok = (p in s) if check == 'Substring' else re.search(p, s) is not None
            reason = '' if ok else (f"the text does not contain '{p}'" if check == 'Substring' else f"the text does not match '{p}'")
            lines = ['Actual:', f"    '{s}'"]
        elif check == 'Fail':
            ok, reason = False, ''
        elif check in ('SameHandle', 'NotSameHandle'):
            same = a[0] is a[1]
            ok = same == (check == 'SameHandle')
            reason = '' if ok else ('they are different objects' if check == 'SameHandle' else 'they are the same object')
        _qualified(kind, tc, ok, check, reason, lines, diag)
        # the function's outputs only when asked for (an anonymous function's value showed as ans after the qualification)
        return result if check in ('Warning', 'WarningFree') and nargout else None
    q.__name__ = name
    q.__doc__ = f'{name}(testCase, ...): see the help.'
    return q


REQ = {'Equal': 2, 'NotEqual': 2, 'True': 1, 'False': 1, 'Error': 2, 'Warning': 2, 'WarningFree': 1, 'Empty': 1, 'NotEmpty': 1,
       'Size': 2, 'Length': 2, 'NumElements': 2, 'Class': 2, 'InstanceOf': 2, 'GreaterThan': 2, 'GreaterThanOrEqual': 2,
       'LessThan': 2, 'LessThanOrEqual': 2, 'ReturnsTrue': 1, 'Substring': 2, 'Matches': 2, 'Fail': 0, 'SameHandle': 2,
       'NotSameHandle': 2}
QUAL_NAMES = [k + c for k in KINDS for c in REQ]
for _k in KINDS:
    for _c in REQ:
        _register(_k + _c, aw=True, nout=99 if _c in ('Warning', 'WarningFree') else 1, arr=False)(_make(_k, _c))
CD.BASE_METHODS[TC_BASE] = set(QUAL_NAMES) | {'log', 'addTeardown'}


@bi('addTeardown')
def addTeardown(nargout, *args):
    """addTeardown(testCase, fh, args...): fh(args...) called when the test ends, the last added first."""
    nargchk(args, 2, 99, 'addTeardown')
    _tc(args[0], 'addTeardown')
    if not isinstance(args[1], FH):
        raise err('MATLAB:unittest:addTeardown:handle', 'addTeardown takes a function handle.', 'addTeardown')
    if RUN['records']:
        RUN['records'][-1].teardowns.append((args[1], args[2:]))
    return None


def _log(nargout, *args):
    """log(testCase, diagnostic), log(testCase, level, diagnostic): a message shown as the test runs (level 1 to 4, 2 when not given; shown up to the run's OutputDetail)."""
    nargchk(args, 2, 3, 'log')
    level = 2
    msg = args[-1]
    if len(args) == 3:
        level = int(num(args[1])) if not is_str(args[1]) else {'terse': 1, 'concise': 2, 'detailed': 3, 'verbose': 4}.get(py_str(args[1]).lower(), 2)
    text = _show(msg) if isinstance(msg, (np.ndarray, float, bool)) else _diag(msg)
    if not RUN['records'] or RUN['detail'] >= level:
        R.write(f'[Logged] {text}\n')
    return None


def _wrap_log():
    info = REG['log']
    orig = info.fn

    def f(nargout, *args):
        if args and _is_tc(args[0]):
            return _log(nargout, *args)
        return orig(nargout, *args)
    info.fn = f


_wrap_log()


# ---- what a suite holds --------------------------------------------------------------------------------------------------------------------

class Entry:
    """A test to run: its kind ('class', 'function', 'script'), its file and the procedure in it."""

    def __init__(self, kind, path, base, proc, **kw):
        self.kind, self.path, self.base, self.proc = kind, path, base, proc
        self.params = kw.get('params') or []          # [(property, value name, value)]
        self.ci = kw.get('ci')
        self.fn = kw.get('fn')
        self.fixtures = kw.get('fixtures') or {}
        self.code = kw.get('code')

    @property
    def name(self):
        p = ''
        if self.params:
            p = '(' + ','.join(f'{prop}={vn}' for prop, vn, _ in self.params) + ')'
        return f'{self.base}/{self.proc}{p}'

    def group(self):
        return (self.kind, self.path)


class Suite(Obj):
    """A test suite: an array of tests."""
    cls = 'matlab.unittest.Test'

    def __init__(self, entries):
        self.entries = list(entries)

    @property
    def shape(self):
        return (1, len(self.entries))

    def index(self, args):
        return Suite([self.entries[i] for i in _positions(args, len(self.entries))])

    def getprop(self, name):
        k = name.lower()
        vals = {'name': lambda e: Char.of(e.name), 'procedurename': lambda e: Char.of(e.proc), 'testclass': lambda e: Char.of(e.base if e.kind == 'class' else ''),
                'basefolder': lambda e: Char.of(os.path.dirname(e.path))}.get(k)
        if vals is None:
            raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'Test'.")
        out_ = [vals(e) for e in self.entries]
        return out_[0] if len(out_) == 1 else Cell.of_list(out_, (1, len(out_)))

    def propnames(self):
        return ['Name', 'ProcedureName', 'TestClass', 'BaseFolder']

    def fld_list(self, name):
        return [Suite([e]).getprop(name) for e in self.entries]

    def display_lines(self):
        n = len(self.entries)
        lines = [f'  1×{n} Test array:' if n != 1 else '  Test:', '']
        lines += [f'    {e.name}' for e in self.entries[:50]]
        if n > 50:
            lines.append(f'    ... ({n - 50} more)')
        return lines


def _positions(args, n):
    if len(args) == 1:
        a = args[0]
        if isinstance(a, np.ndarray) and a.dtype == bool:
            return list(np.flatnonzero(a.reshape(-1, order='F')))
        if isinstance(a, Char) and a.str() == ':':
            return list(range(n))
        ids = np.asarray(darr(a)).reshape(-1)
        if np.any(ids < 1) or np.any(ids > n) or np.any(ids != np.round(ids)):
            raise MError('MATLAB:badsubscript', f'Index exceeds the number of array elements ({n}).')
        return [int(i) - 1 for i in ids]
    if len(args) == 2:
        return _positions(args[1:], n)
    raise MError('MATLAB:badsubscript', 'A test array takes one index.')


class Result(Obj):
    """TestResult: an array of the outcomes of tests."""
    cls = 'matlab.unittest.TestResult'
    KEYS = ('Name', 'Passed', 'Failed', 'Incomplete', 'Duration', 'Details')

    def __init__(self, recs):
        self.recs = list(recs)

    @property
    def shape(self):
        return (1, len(self.recs))

    def index(self, args):
        return Result([self.recs[i] for i in _positions(args, len(self.recs))])

    def one(self, rec, k):
        if k == 'Name':
            return Char.of(rec.name)
        if k in ('Passed', 'Failed', 'Incomplete'):
            return {'Passed': rec.passed, 'Failed': rec.failed, 'Incomplete': rec.incomplete}[k]
        if k == 'Duration':
            return float(rec.duration)
        diags = rec.failures + ([rec.failures_assumed] if getattr(rec, 'failures_assumed', None) else [])
        return Struct.scalar({'Diagnostics': Cell.of_list([Char.of(t) for t in diags], (len(diags), 1))})

    def getprop(self, name):
        k = next((x for x in self.KEYS if x.lower() == name.lower()), None)
        if k is None:
            raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'TestResult'.")
        vals = [self.one(r, k) for r in self.recs]
        if len(vals) == 1:
            return vals[0]
        if k in ('Passed', 'Failed', 'Incomplete'):
            return np.array([vals], bool)
        if k == 'Duration':
            return np.array([vals], float)
        return Cell.of_list(vals, (1, len(vals)))

    def propnames(self):
        return list(self.KEYS)

    def fld_list(self, name):
        return [Result([r]).getprop(name) for r in self.recs]

    def totals(self):
        p = sum(r.passed for r in self.recs)
        f = sum(r.failed for r in self.recs)
        i = sum(r.incomplete and not r.failed for r in self.recs)
        t = sum(r.duration for r in self.recs)
        return ['Totals:', f'   {p} Passed, {f} Failed, {i} Incomplete.', f'   {t:.4g} seconds testing time.']

    def display_lines(self):
        n = len(self.recs)
        if n == 1:
            r = self.recs[0]
            from ..display import summary
            w = max(len(k) for k in self.KEYS)
            lines = ['  TestResult with properties:', '']
            for k in self.KEYS:
                v = self.one(r, k)
                lines.append(f'    {k.rjust(w)}: {"true" if v is True else "false" if v is False else summary(v)}')
            return lines + [''] + self.totals()
        return [f'  1×{n} TestResult array with properties:', ''] + [f'    {k}' for k in self.KEYS] + [''] + self.totals()


def _join(op, *xs):
    if op in ('hcat', 'vcat'):
        kinds = [type(x) for x in xs if numel(x) or isinstance(x, (Suite, Result))]
        if all(k is Result for k in kinds):
            return Result([r for x in xs if isinstance(x, Result) for r in x.recs])
        if all(k is Suite for k in kinds):
            return Suite([e for x in xs if isinstance(x, Suite) for e in x.entries])
    raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for tests and their results.")


def _register_ops():
    from ..ops import OBJ_OPS
    OBJ_OPS[Suite] = _join
    OBJ_OPS[Result] = _join


_register_ops()


# ---- finding tests -------------------------------------------------------------------------------------------------------------------------

def _testlike(name):
    n = name.lower()
    return n.startswith('test') or n.endswith('test')


def _class_methods(ci):
    """Every method of a class and its superclasses (the subclass's own last, replacing theirs)."""
    out_ = {}
    for s in ci.supers:
        out_.update(_class_methods(s))
    out_.update(ci.methods)
    return out_


def _param_values(ci, prop):
    p = ci.find_prop(prop)
    if p is None or not p['attrs'].get('testparameter'):
        return None
    v = p['default']
    if isinstance(v, Struct) and v.size == 1:
        return [(k, v.get1(k)) for k in v.keys]
    if isinstance(v, Cell):
        items = list(v.a.reshape(-1, order='F'))
        out_ = []
        for k, x in enumerate(items):
            if isinstance(x, Char) and 0 < x.a.size <= 30:
                nm = x.str()
            elif type(x) in (float, bool) or (isinstance(x, np.ndarray) and x.size == 1):
                nm = f'{float(np.asarray(x).reshape(-1)[0]):g}'
            else:
                nm = f'value{k + 1}'
            out_.append((nm, x))
        return out_
    return [('value1', v)]


def _class_entries(ci, path):
    base = ci.name
    out_ = []
    for mname, m in _class_methods(ci).items():
        if not m['attrs'].get('test'):
            continue
        params = m.get('params', [])[1:]
        choices = []
        for prop in params:
            vals = _param_values(ci, prop)
            if vals is None:
                raise err('MATLAB:unittest:TestParameter', f"The test {base}/{mname} takes '{prop}', which is no TestParameter property of the class.", 'runtests')
            choices.append([(prop, vn, v) for vn, v in vals])
        for combo in itertools.product(*choices) if choices else [()]:
            out_.append(Entry('class', path, base, mname, ci=ci, params=list(combo)))
    return out_


def _script_entries(path, text):
    base = os.path.splitext(os.path.basename(path))[0]
    lines = text.split('\n')
    starts = [i for i, ln in enumerate(lines) if re.match(r'\s*%%(\s|$)', ln)]
    if not starts:
        return [Entry('script', path, base, base, code=(text, ''))]
    shared = '\n'.join(lines[:starts[0]])
    out_ = []
    used = set()
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(lines)
        title = re.sub(r'^\s*%%', '', lines[s]).strip()
        nm = re.sub(r'\W+', '_', title).strip('_') if title else f'Test{k + 1}'
        if nm and nm[0].isdigit():
            nm = 'x' + nm
        nm = nm or f'Test{k + 1}'
        while nm in used:
            nm += '_'
        used.add(nm)
        # the section at its own lines of the file, so that errors give the file's line numbers
        body = '\n' * (s - starts[0] + 1) + '\n'.join(lines[s + 1:e])
        out_.append(Entry('script', path, base, nm, code=(shared, body)))
    return out_


async def _file_entries(path, explicit):
    """The tests of a file: a test class, a function file that gives functiontests, or a script."""
    base = os.path.splitext(os.path.basename(path))[0]
    text = R.read_source(path)
    if CD.is_classdef(text):
        mod = R.load_file(path)
        ci = getattr(mod, 'classinfo', None)
        if ci is None or TC_BASE not in ci.all_names():
            if explicit:
                raise err('MATLAB:unittest:notATestClass', f"The class {base} is not a test class (classdef {base} < matlab.unittest.TestCase).", 'runtests')
            return []
        return _class_entries(ci, path)
    if not explicit and not _testlike(base):
        return []
    mod = R.load_file(path)
    if mod.kind == 'function':
        prog = getattr(mod, 'prog', None)
        first = prog.funcs[0] if prog is not None and prog.funcs else None
        if first is None or [p for p in first.params if p != 'varargin'] or not first.outs:
            # a function that takes inputs, or gives nothing, is no test file
            if explicit:
                raise err('MATLAB:unittest:notATestFunction', f'The function {base} does not give tests (tests = functiontests(localfunctions)).', 'runtests')
            return []
        main = mod.ns.get('MAIN')
        suite = await main(1)
        if not isinstance(suite, Suite):
            if explicit:
                raise err('MATLAB:unittest:notATestFunction', f'The function {base} does not give tests (tests = functiontests(localfunctions)).', 'runtests')
            return []
        return suite.entries
    return _script_entries(path, text)


def _cwd():
    return R.STATE.get('cwd') or os.getcwd()


async def _entries_for(target, subfolders):
    """Tests named: a file, a folder, a class or function on the path, each perhaps with /procedure."""
    t = target
    proc = None
    full = t if os.path.isabs(t) else os.path.join(_cwd(), t)
    if not os.path.exists(full) and '/' in t and not t.endswith('/'):
        head, proc = t.rsplit('/', 1)
        t = head
        full = t if os.path.isabs(t) else os.path.join(_cwd(), t)
    if os.path.isdir(full):
        found = []
        for root, dirs, files in os.walk(full):
            dirs[:] = sorted(d for d in dirs if subfolders and not d.startswith(('.', '+', '@', 'private')))
            for f in sorted(files):
                if f.endswith('.m'):
                    found += await _file_entries(os.path.join(root, f), False)
            if not subfolders:
                break
        entries = found
    else:
        path = None
        if os.path.isfile(full):
            path = full
        elif os.path.isfile(full + '.m'):
            path = full + '.m'
        else:
            path = R.find_file(os.path.splitext(t)[0])
        if path is None:
            raise err('MATLAB:unittest:noTests', f"There is no test file, folder or class named '{target}'.", 'runtests')
        entries = await _file_entries(path, True)
    if proc is not None:
        entries = [e for e in entries if e.proc == proc or fnmatch.fnmatchcase(e.name, f'*/{proc}')]
        if not entries:
            raise err('MATLAB:unittest:noTests', f"There is no test '{target}'.", 'runtests')
    return entries


def _names_arg(v):
    if isinstance(v, Char):
        return [v.str()]
    return [str(x) for x in text_list(v)]


OPTS = ('includesubfolders', 'name', 'procedurename', 'outputdetail', 'strict', 'useparallel', 'debug', 'logginglevel', 'recursively', 'baseFolder'.lower())


async def _gather(args, fn):
    """Positional names (none: the current folder) and options: (entries, detail)."""
    a = list(args)
    names = []
    while a and not (is_str(a[0]) and py_str(a[0]).lower() in OPTS and len(a) >= 2 and len(a) % 2 == 0):
        x = a.pop(0)
        if isinstance(x, Suite):
            names.append(x)
        else:
            names += _names_arg(x)
    o = {}
    if len(a) % 2:
        raise err(f'MATLAB:{fn}:pairs', f'The options of {fn} come as names and values.', fn)
    for i in range(0, len(a), 2):
        k = py_str(a[i]).lower()
        if k not in OPTS:
            raise err(f'MATLAB:{fn}:option', f"'{py_str(a[i])}' is not an option of {fn}.", fn)
        o[k] = a[i + 1]
    sub = bool(np.all(o['includesubfolders'])) if 'includesubfolders' in o and not is_str(o['includesubfolders']) else False
    entries = []
    for nm in names or [_cwd()]:
        entries += nm.entries if isinstance(nm, Suite) else await _entries_for(nm, sub)
    if 'name' in o:
        pats = _names_arg(o['name'])
        entries = [e for e in entries if any(fnmatch.fnmatchcase(e.name, p) for p in pats)]
    if 'procedurename' in o:
        pats = _names_arg(o['procedurename'])
        entries = [e for e in entries if any(fnmatch.fnmatchcase(e.proc, p) for p in pats)]
    return entries, _detail(o.get('outputdetail'))


def _detail(v):
    if v is None:
        return 2
    if is_str(v):
        return {'none': 0, 'terse': 1, 'concise': 2, 'detailed': 3, 'verbose': 4}.get(py_str(v).lower(), 2)
    return int(num(v))


# ---- running --------------------------------------------------------------------------------------------------------------------------

async def _call_method(obj, m, *args):
    return await m['fn'](0, obj, *args)


def _methods_with(ci, attr, reverse=False):
    ms = [(n, m) for n, m in _class_methods(ci).items() if m['attrs'].get(attr)]
    return list(reversed(ms)) if reverse else ms


async def _guard(rec, coro_fn):
    """Run a part of a test; an error or a failed assertion recorded. False when the test must end."""
    try:
        await coro_fn()
        return True
    except Abort as e:
        if e.kind == 'fatalAssert':
            RUN['fatal'] = True
        return False
    except MError as e:
        ident = getattr(e, 'identifier', '') or ''
        msg = e.message if hasattr(e, 'message') else str(e)
        text = f'Error occurred in {rec.name} and it did not run to completion.\n    Error ID: {ident or "(none)"}\n    Error message: {msg}'
        rec.failures.append(text)
        rec.reasons.append('error')
        if RUN['detail'] >= 1:
            R.write(f'\n{RULE}\n{text}\n{RULE}\n')
        return False


async def _teardowns(rec):
    while rec.teardowns:
        f, a = rec.teardowns.pop()
        await _guard(rec, lambda f=f, a=a: f.acall(0, *a))


async def _run_group(entries, out_recs):
    first = entries[0]
    kind = first.kind
    if RUN['detail'] >= 1:
        R.write(f'Running {first.base}\n')
    dots = 0

    def done_one(rec):
        nonlocal dots
        out_recs.append(rec)
        if RUN['detail'] >= 1:
            R.write('.')
            dots += 1
            if dots % 50 == 0:
                R.write('\n')

    if kind == 'class':
        ci = first.ci
        shared = await R.call(None, ci.name, 1, ())
        setup_rec = Record(first.base)
        RUN['records'].append(setup_rec)
        ok = True
        try:
            for _, m in _methods_with(ci, 'testclasssetup'):
                ok = await _guard(setup_rec, lambda m=m: _call_method(shared, m))
                if not ok:
                    break
        finally:
            RUN['records'].pop()
        for e in entries:
            rec = Record(e.name)
            if not ok or RUN.get('fatal'):
                rec.failures += setup_rec.failures or []
                rec.incomplete = not setup_rec.failures
                rec.reasons.append('class setup' if setup_rec.failures else 'not run')
                out_recs.append(rec)
                continue
            tc = CD.UObj(ci)
            tc.p = dict(shared.p)
            RUN['records'].append(rec)
            t0 = time.perf_counter()
            try:
                good = True
                for _, m in _methods_with(ci, 'testmethodsetup'):
                    good = await _guard(rec, lambda m=m: _call_method(tc, m))
                    if not good:
                        break
                if good:
                    m = _class_methods(ci)[e.proc]
                    await _guard(rec, lambda m=m: _call_method(tc, m, *[v for _, _, v in e.params]))
                await _teardowns(rec)
                for _, m in _methods_with(ci, 'testmethodteardown', reverse=True):
                    await _guard(rec, lambda m=m: _call_method(tc, m))
            finally:
                rec.duration = time.perf_counter() - t0
                RUN['records'].pop()
            done_one(rec)
        RUN['records'].append(setup_rec)
        try:
            for _, m in _methods_with(ci, 'testclassteardown', reverse=True):
                await _guard(setup_rec, lambda m=m: _call_method(shared, m))
        finally:
            RUN['records'].pop()
    elif kind == 'function':
        fx = first.fixtures
        shared = FunctionTestCase()
        once = Record(first.base)
        RUN['records'].append(once)
        ok = True
        try:
            if 'setupOnce' in fx:
                ok = await _guard(once, lambda: fx['setupOnce'].acall(0, shared))
        finally:
            RUN['records'].pop()
        for e in entries:
            rec = Record(e.name)
            if not ok or RUN.get('fatal'):
                rec.failures += once.failures
                rec.incomplete = not once.failures
                out_recs.append(rec)
                continue
            tc = FunctionTestCase(shared.data)
            RUN['records'].append(rec)
            t0 = time.perf_counter()
            try:
                good = True
                if 'setup' in fx:
                    good = await _guard(rec, lambda: fx['setup'].acall(0, tc))
                if good:
                    await _guard(rec, lambda: e.fn.acall(0, tc))
                await _teardowns(rec)
                if 'teardown' in fx:
                    await _guard(rec, lambda: fx['teardown'].acall(0, tc))
            finally:
                rec.duration = time.perf_counter() - t0
                RUN['records'].pop()
            done_one(rec)
        if 'teardownOnce' in fx:
            RUN['records'].append(once)
            try:
                await _guard(once, lambda: fx['teardownOnce'].acall(0, shared))
            finally:
                RUN['records'].pop()
    else:
        for e in entries:
            rec = Record(e.name)
            if RUN.get('fatal'):
                rec.incomplete = True
                out_recs.append(rec)
                continue
            shared_code, body = e.code
            W = R.Workspace(e.base)

            async def go(text=shared_code + '\n' + body, W=W):
                fn, _ = R.compile_command(text, W)
                await fn(W)
            RUN['records'].append(rec)
            t0 = time.perf_counter()
            try:
                await _guard(rec, go)
            finally:
                rec.duration = time.perf_counter() - t0
                RUN['records'].pop()
            done_one(rec)
    if RUN['detail'] >= 1:
        R.write(f'\nDone {first.base}\n__________\n\n')


async def run_entries(entries, detail=2):
    old_detail = RUN['detail']
    RUN['detail'] = detail
    RUN['fatal'] = False
    recs = []
    try:
        groups = []
        for e in entries:
            if groups and groups[-1][0].group() == e.group():
                groups[-1].append(e)
            else:
                groups.append([e])
        for g in groups:
            await _run_group(g, recs)
        bad = [r for r in recs if not r.passed]
        if bad and detail >= 1:
            w = max(max(len(r.name) for r in bad), 4)
            lines = ['Failure Summary:', '', f'     {"Name".ljust(w)}  Failed  Incomplete  Reason(s)', '    ' + '=' * (w + 36)]
            for r in bad:
                why = sorted(set(r.reasons))
                text = ', '.join({'verification': 'Failed by verification', 'assertion': 'Failed by assertion', 'fatal assertion': 'Failed by fatal assertion',
                                  'error': 'Errored', 'assumption': 'Filtered by assumption', 'class setup': 'Class setup failed',
                                  'not run': 'Not run'}.get(x, x) for x in why)
                lines.append(f'     {r.name.ljust(w)}  {"X" if r.failed else " ":^6}  {"X" if r.incomplete else " ":^10}  {text}.')
            R.write('\n'.join(lines) + '\n')
    finally:
        RUN['detail'] = old_detail
        RUN['fatal'] = False
    return Result(recs)


# ---- the functions ------------------------------------------------------------------------------------------------------------------------

@bi('runtests', aw=True)
async def runtests(nargout, *args):
    """results = runtests, runtests(names), runtests(..., 'IncludeSubfolders', true, 'Name', pattern, 'ProcedureName', pattern, 'OutputDetail', level): run tests and give their results."""
    entries, detail = await _gather(args, 'runtests')
    return await run_entries(entries, detail)


@bi('testsuite', aw=True)
async def testsuite(nargout, *args):
    """suite = testsuite, testsuite(names, Name, Value): the tests runtests would run, to run later (run(suite))."""
    entries, _ = await _gather(args, 'testsuite')
    return Suite(entries)


async def _from(nargout, *args):
    # a class given by its meta.class object (fromClass(?SampleTest)) is taken by its name
    args = tuple(x.getprop('Name') if getattr(x, 'cls', None) == 'meta.class' else x for x in args)
    entries, _ = await _gather(args, 'TestSuite')
    return Suite(entries)


for _n in ('fromFile', 'fromFolder', 'fromName', 'fromClass'):
    _register(f'matlab.unittest.TestSuite.{_n}', aw=True, arr=False)(_from)


@bi('functiontests')
def functiontests(nargout, *args):
    """tests = functiontests(localfunctions): a function file's tests: its local functions whose names start or end with 'test', and setupOnce, teardownOnce, setup and teardown."""
    nargchk(args, 1, 1, 'functiontests')
    fhs = args[0]
    items = [x for x in fhs.a.reshape(-1, order='F')] if isinstance(fhs, Cell) else [fhs]
    if not all(isinstance(x, R.NamedFH) for x in items):
        raise err('MATLAB:unittest:functiontests:handles', 'functiontests takes the local functions of a test file (localfunctions).', 'functiontests')
    path, base = '', 'tests'
    for x in items:
        target = getattr(x, 'target', None)
        code = getattr(target, '__code__', None)
        if code is not None and code.co_filename in R.MODULES:
            mod = R.MODULES[code.co_filename]
            path, base = mod.path, mod.name
            break
    fixtures = {}
    tests = []
    for x in items:
        nm = x.fname
        if nm in ('setupOnce', 'teardownOnce', 'setup', 'teardown'):
            fixtures[nm] = x
        elif _testlike(nm):
            tests.append(x)
    return Suite([Entry('function', path, base, x.fname, fn=x, fixtures=fixtures) for x in tests])


@bi('localfunctions')
def localfunctions(nargout, *args):
    """fhs = localfunctions: handles to the local functions of the file it is called in (its first function left out)."""
    nargchk(args, 0, 0, 'localfunctions')
    import sys
    f = sys._getframe(1)
    while f is not None:
        fn = f.f_code.co_filename
        if fn.startswith('<plab:') and fn in R.MODULES and R.MODULES[fn].path != 'command':
            mod = R.MODULES[fn]
            prog = getattr(mod, 'prog', None)
            names = [fd.name for fd in prog.funcs[1:]] if prog is not None else []
            fhs = [R.LocalFH(n, mod.ns['LF_' + n]) for n in names if 'LF_' + n in mod.ns]
            return Cell.of_list(fhs, (len(fhs), 1))
        f = f.f_back
    return Cell.empty((0, 1))


@bi('matlab.unittest.TestCase.forInteractiveUse')
def for_interactive(nargout, *args):
    """testCase = matlab.unittest.TestCase.forInteractiveUse: a test case whose qualifications print whether they passed, for trying them at the prompt."""
    return InteractiveTestCase()


@bi('assertSuccess')
def assertSuccess(nargout, *args):
    """results = assertSuccess(results): an error if a test failed or did not run to the end."""
    nargchk(args, 1, 2, 'assertSuccess')
    r = args[0]
    if not isinstance(r, Result):
        raise err('MATLAB:unittest:assertSuccess:results', 'assertSuccess takes test results (from runtests).', 'assertSuccess')
    bad = [x for x in r.recs if not x.passed]
    if bad:
        names = '\n'.join(f'    {x.name}' for x in bad)
        raise MError('MATLAB:unittest:TestResult:AssertSuccessFailed', f'{len(bad)} of {len(r.recs)} tests failed or did not run to the end:\n{names}')
    return r


class Runner(Obj):
    cls = 'matlab.unittest.TestRunner'
    is_handle = True

    def __init__(self, detail):
        self.detail = detail

    def getprop(self, name):
        if name == 'run':
            runner = self

            class _Run(FH):
                def text(self):
                    return '@run'

                def name(self):
                    return 'run'

                async def acall(self, nargout, *args):
                    return await _run_with(runner, args)
            return _Run()
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class 'TestRunner'.")

    def display_lines(self):
        return ['  TestRunner' + (' with text output' if self.detail else ' without output')]


async def _run_with(runner, args):
    if not args or not isinstance(args[0], Suite):
        raise err('MATLAB:unittest:TestRunner:suite', 'A test runner runs a test suite (from testsuite).', 'run')
    return await run_entries(args[0].entries, runner.detail)


@bi('matlab.unittest.TestRunner.withTextOutput')
def with_text(nargout, *args):
    """runner = matlab.unittest.TestRunner.withTextOutput('OutputDetail', level): a runner that reports as runtests does."""
    d = 2
    for i in range(0, len(args) - 1, 2):
        if py_str(args[i]).lower() == 'outputdetail':
            d = _detail(args[i + 1])
    return Runner(d)


@bi('matlab.unittest.TestRunner.withNoPlugins')
def with_none(nargout, *args):
    """runner = matlab.unittest.TestRunner.withNoPlugins: a runner that runs tests silently."""
    return Runner(0)


async def _run_tests(W, nargout, first, *rest):
    if isinstance(first, Runner):
        return await _run_with(first, rest)
    if isinstance(first, Suite):
        return await run_entries(first.entries, 2)
    ci = first.ci
    entries = _class_entries(ci, ci.path)
    if rest:
        want = py_str(rest[0])
        entries = [e for e in entries if e.proc == want]
        if not entries:
            raise err('MATLAB:unittest:noTests', f"The class {ci.name} has no test '{want}'.", 'run')
    return await run_entries(entries, 2)


def _wrap_run():
    info = REG['run']
    orig = info.fn

    async def f(W, nargout, *args):
        if args and (isinstance(args[0], (Suite, Runner)) or (isinstance(args[0], CD.UObj) and TC_BASE in args[0].ci.all_names())):
            return await _run_tests(W, nargout, *args)
        return await orig(W, nargout, *args)
    info.fn = f


_wrap_run()


def _wrap_table():
    info = REG['table']
    orig = info.fn

    def f(nargout, *args):
        real = [a for a in args if type(a).__name__ != 'ArgNames']
        if len(real) == 1 and isinstance(real[0], Result):
            from .tables import Table
            recs = real[0].recs
            n = len(recs)
            names = Str.from_list([r.name for r in recs], (n, 1))
            cols = [names, np.array([[r.passed] for r in recs], bool).reshape(n, 1), np.array([[r.failed] for r in recs], bool).reshape(n, 1),
                    np.array([[r.incomplete] for r in recs], bool).reshape(n, 1), np.array([[r.duration] for r in recs], float).reshape(n, 1),
                    Cell.of_list([real[0].one(r, 'Details') for r in recs], (n, 1))]
            return Table(cols, list(Result.KEYS), None, n)
        return orig(nargout, *args)
    info.fn = f


_wrap_table()
