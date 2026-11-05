"""Unit tests and calling Python, run natively (CPython with numpy): test
classes (setups, teardowns, parameters, every outcome), function-based and
script-based tests, the qualifications one by one (each kind passing and
failing), runtests' options, suites and runners, TestResult and its table;
then py.module.function calls, the conversions both ways, pyrun and
pyrunfile, pyenv and pyargs, and Python errors as the language's.

    python3 test_unittests.py          (from any folder)
"""
import asyncio
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-unittests-')


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
        return np.concatenate([np.asarray(v, dtype=float).reshape(-1) for v in x])
    return np.asarray(x, dtype=float)


def near(label, got, want, tol=1e-12):
    g, w = a(got), a(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {g.tolist() if g.size < 40 else g.shape}, want {w.tolist() if w.size < 40 else w.shape}')


def same(label, got, want):
    return C(label, got == want, f'got {got!r}, want {want!r}')


def text(v):
    from plab.values import py_str
    return v.str() if isinstance(v, Char) else py_str(v)


def texts(v):
    return [text(x) for x in v.a.reshape(-1, order='F')]


def write(name, body):
    path = os.path.join(TMP, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(body)


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = W['e'].str() if isinstance(W['e'], Char) else str(W['e'])
    return C(f'refused: {code}', words in msg, msg)


write('SampleTest.m', """classdef SampleTest < matlab.unittest.TestCase
    properties
        Data
        Log = {}
    end
    properties (TestParameter)
        n = {1, 2, 3};
        kind = struct('small', 0.1, 'large', 10);
    end
    methods (TestClassSetup)
        function prepare(testCase)
            testCase.Data = magic(3);
        end
    end
    methods (TestMethodSetup)
        function each(testCase)
            testCase.addTeardown(@() fprintf('down '));
        end
    end
    methods (TestMethodTeardown)
        function after(testCase)
            fprintf('after ');
        end
    end
    methods (Test)
        function testSum(testCase)
            testCase.verifyEqual(sum(testCase.Data(:)), 45);
        end
        function testFails(testCase)
            testCase.verifyEqual([1 2 3], [1 2.5 3]);
            verifyTrue(testCase, false, 'my own words');
            fprintf('went on ');
        end
        function testAsserts(testCase)
            testCase.assertEqual(1, 2);
            fprintf('NOT REACHED ');
        end
        function testAssume(testCase)
            testCase.assumeTrue(false);
            testCase.verifyFail();
        end
        function testParam(testCase, n)
            testCase.verifyLessThan(n, 3);
        end
        function testTwo(testCase, n, kind)
            testCase.verifyGreaterThan(n * kind, 0);
        end
        function testCrash(testCase)
            x = [1 2];
            y = x(5);
        end
    end
end
""")
write('fnTest.m', """function tests = fnTest
tests = functiontests(localfunctions);
end

function setupOnce(testCase)
testCase.TestData.base = 10;
end

function setup(testCase)
testCase.TestData.count = 1;
end

function testAdd(testCase)
verifyEqual(testCase, testCase.TestData.base + testCase.TestData.count, 11);
end

function testWarn(testCase)
r = verifyWarning(testCase, @() warnAndGive(), 'a:b');
verifyEqual(testCase, r, 7);
end

function testWarnFree(testCase)
verifyWarningFree(testCase, @() 1 + 1);
end

function v = warnAndGive()
warning('a:b', 'careful');
v = 7;
end
""")
write('scriptTest.m', """x = 2;
%% Square
assert(x^2 == 4)
%% Cube fails
assert(x^3 == 9, 'not nine')
%% Square
assert(true)
""")
write('sub/innerTest.m', """%% Inner
assert(1 == 1)
""")
write('FatalTest.m', """classdef FatalTest < matlab.unittest.TestCase
    methods (Test)
        function testA(testCase)
            testCase.fatalAssertTrue(false);
        end
        function testB(testCase)
            testCase.verifyTrue(true);
        end
    end
end
""")
write('helper.m', "function y = helper(x)\ny = x;\nend\n")

# ---- test classes ----------------------------------------------------------------------------------------------------------------------
W, out = run("r = runtests('SampleTest'); n = numel(r); p = [r.Passed]; f = [r.Failed]; i = [r.Incomplete]; names = {r.Name}; d = r(2).Details; dd = d.Diagnostics; "
             "t = table(r); tn = t.Properties.VariableNames; th = height(t); dur = all([r.Duration] >= 0);")
near('runtests of a class: 3 parameter values and 6 combinations make 14 tests', W['n'], 14)
same('the tests named after their parameters', texts(W['names'])[4:9], ['SampleTest/testParam(n=1)', 'SampleTest/testParam(n=2)', 'SampleTest/testParam(n=3)',
                                                                        'SampleTest/testTwo(n=1,kind=small)', 'SampleTest/testTwo(n=1,kind=large)'])
P = list(np.asarray(W['p'], bool).reshape(-1))
F = list(np.asarray(W['f'], bool).reshape(-1))
I_ = list(np.asarray(W['i'], bool).reshape(-1))
names = texts(W['names'])
outcome = {nm: (p, f, i) for nm, p, f, i in zip(names, P, F, I_)}
same('a passing test', outcome['SampleTest/testSum'], (True, False, False))
same('verification failures: failed, the test went on', (outcome['SampleTest/testFails'], 'went on' in out), ((False, True, False), True))
same('an assertion ends the test, failed', (outcome['SampleTest/testAsserts'], 'NOT REACHED' in out), ((False, True, False), False))
same('an assumption: incomplete, not failed', outcome['SampleTest/testAssume'], (False, False, True))
same('a parameter value failing', (outcome['SampleTest/testParam(n=3)'], outcome['SampleTest/testParam(n=2)']), ((False, True, False), (True, False, False)))
same('an error in the test: failed', outcome['SampleTest/testCrash'], (False, True, False))
same('the failures shown as they happen, with the diagnostics', all(s in out for s in ('Verification failed in SampleTest/testFails.', 'my own words', 'Actual:', '[1 2.5 3]',
                                                                                       'Assertion failed in SampleTest/testAsserts.', 'Error occurred in SampleTest/testCrash',
                                                                                       'MATLAB:badsubscript')), True)
same('the run framed by Running and Done, a failure summary at the end', all(s in out for s in ('Running SampleTest', 'Done SampleTest', 'Failure Summary:', 'Filtered by assumption.',
                                                                                                'Failed by verification.', 'Failed by assertion.', 'Errored.')), True)
same('teardowns: addTeardown first, then TestMethodTeardown, for every test', out.count('down after ') == 14, True)
same('Details holds the failure texts', len(W['dd'].a) == 2 and 'my own words' in text(W['dd'].a[1, 0]), True)
same('table(results): a row each, the properties as variables', (texts(W['tn']), W['th']), (['Name', 'Passed', 'Failed', 'Incomplete', 'Duration', 'Details'], 14.0))
W, out = run("r = runtests('SampleTest/testSum'); n = numel(r); r2 = runtests('SampleTest', 'Name', '*testTwo*large*'); n2 = numel(r2); "
             "r3 = runtests('SampleTest', 'ProcedureName', 'testParam'); n3 = numel(r3); r4 = runtests('SampleTest', 'OutputDetail', 'None'); "
             "r5 = run(SampleTest, 'testSum'); n5 = numel(r5); r6 = run(SampleTest); n6 = numel(r6);")
near("one test by name; 'Name' and 'ProcedureName' patterns; run of a test object", (W['n'], W['n2'], W['n3'], W['n5'], W['n6']), (1, 3, 3, 1, 14))
W, out = run("r = runtests('SampleTest', 'OutputDetail', 'None');")
same("'OutputDetail' 'None': nothing shown", 'Running' in out or 'Failure Summary' in out, False)
W, out = run("r = runtests('FatalTest'); i = [r.Incomplete]; f = [r.Failed];")
near('a fatal assertion: that test failed, the rest of the run not run', (W['f'], W['i']), ([1, 0], [0, 1]))

# ---- function-based and script-based tests ---------------------------------------------------------------------------------------------------
W, out = run("r = runtests('fnTest'); p = [r.Passed]; names = {r.Name};")
same('function-based: the local functions named test..., setupOnce and setup sharing TestData', (texts(W['names']), list(np.asarray(W['p'], bool).reshape(-1))),
     (['fnTest/testAdd', 'fnTest/testWarn', 'fnTest/testWarnFree'], [True, True, True]))
same('verifyWarning keeps the warning from the Command Window and gives the outputs', 'careful' in out, False)
W, out = run("r = runtests('scriptTest'); p = [r.Passed]; names = {r.Name};")
same('script-based: a test for each %% section, the shared code before each, names made unique', (texts(W['names']), list(np.asarray(W['p'], bool).reshape(-1))),
     (['scriptTest/Square', 'scriptTest/Cube_fails', 'scriptTest/Square_'], [True, False, True]))
same('an assert in a script test shows its message', 'not nine' in out, True)
W, out = run("r = runtests(pwd); names = {r.Name}; r2 = runtests(pwd, 'IncludeSubfolders', true); n2 = numel(r2);")
nm = texts(W['names'])
same('runtests of a folder: test classes, and the files named ...test (helper.m left out)', (any(x.startswith('SampleTest/') for x in nm), any(x.startswith('fnTest/') for x in nm),
                                                                                              any(x.startswith('scriptTest/') for x in nm), any('helper' in x for x in nm), any('inner' in x for x in nm)),
     (True, True, True, False, False))
near("'IncludeSubfolders' finds the test in sub/", W['n2'], len(nm) + 1)

# ---- suites, runners, results ------------------------------------------------------------------------------------------------------------
W, out = run("s = testsuite('scriptTest'); n = numel(s); nm = s(2).Name; r = run(s(1)); p = r.Passed; "
             "s2 = matlab.unittest.TestSuite.fromFile('fnTest.m'); both = [s s2]; nb = numel(both); "
             "runner = matlab.unittest.TestRunner.withNoPlugins; r3 = runner.run(both); n3 = numel(r3); "
             "r4 = run(matlab.unittest.TestRunner.withTextOutput, s2); rr = [r r4]; nrr = numel(rr); "
             "try, assertSuccess(r3); ok = 1; catch ex, ok = 0; msg = ex.message; end; assertSuccess(r4); ")
near('testsuite, indexing it, running one; fromFile; concatenating suites and results', (W['n'], W['p'], W['nb'], W['n3'], W['nrr'], W['ok']), (3, 1, 6, 6, 4, 0))
same('a suite element has its name; assertSuccess names what failed', (text(W['nm']), 'scriptTest/Cube_fails' in text(W['msg'])), ('scriptTest/Cube_fails', True))
same('withNoPlugins runs silently, withTextOutput reports', out.count('Running scriptTest') == 1 and out.count('Running fnTest') == 1, True)
W, out = run("tc = matlab.unittest.TestCase.forInteractiveUse; verifyWarningFree(tc, @() 1 + 1)\nv = verifyWarningFree(tc, @() 1 + 1);")
same("verifyWarningFree gives the function's value only when asked for (it showed ans = 2)", ('ans' in out, float(a(W['v']))), (False, 2.0))
W, out = run("s1 = matlab.unittest.TestSuite.fromClass(?SampleTest); s2 = matlab.unittest.TestSuite.fromClass('SampleTest'); same = isequal({s1.Name}, {s2.Name}); n = numel(s1);")
same('TestSuite.fromClass of a meta.class object (?SampleTest), as of its name (it was refused)', (bool(W['same']), int(a(W['n'])) > 1), (True, True))
W, out = run("r = runtests('fnTest')")
same('results shown with their totals', all(s in out for s in ('1×3 TestResult array with properties:', 'Totals:', '3 Passed, 0 Failed, 0 Incomplete.', 'seconds testing time.')), True)

# ---- the qualifications, one by one, at the prompt ----------------------------------------------------------------------------------------------
cases = [
    ("verifyEqual(tc, [1 NaN], [1 NaN])", True), ("verifyEqual(tc, 1, int8(1))", False), ("verifyEqual(tc, [1 2], [1 2]')", False),
    ("verifyEqual(tc, 1.05, 1, 'AbsTol', 0.1)", True), ("verifyEqual(tc, 1.2, 1, 'RelTol', 0.1)", False), ("verifyEqual(tc, {1, 'a'}, {1, 'a'})", True),
    ("verifyEqual(tc, struct('a', 1, 'b', 2), struct('b', 2, 'a', 1))", True), ("verifyEqual(tc, struct('a', {1, 2}), struct('a', {1, 3}))", False),
    ("verifyEqual(tc, \"x\", 'x')", False), ("verifyNotEqual(tc, 1, 2)", True), ("verifyNotEqual(tc, 'a', 'a')", False),
    ("verifyTrue(tc, true)", True), ("verifyTrue(tc, 1)", False), ("verifyFalse(tc, false)", True), ("verifyFalse(tc, [false false])", False),
    ("verifyError(tc, @() error('x:y', 'z'), 'x:y')", True), ("verifyError(tc, @() error('x:y', 'z'), 'x:w')", False), ("verifyError(tc, @() 1, 'x:y')", False),
    ("verifyWarning(tc, @() warning('w:v', 'hm'), 'w:v')", True), ("verifyWarning(tc, @() 1, 'w:v')", False), ("verifyWarningFree(tc, @() warning('w:v', 'hm'))", False),
    ("verifyEmpty(tc, zeros(0, 3))", True), ("verifyEmpty(tc, 0)", False), ("verifyNotEmpty(tc, 'a')", True), ("verifySize(tc, ones(2, 3), [2 3])", True),
    ("verifySize(tc, ones(2, 3), [3 2])", False), ("verifyLength(tc, ones(2, 5), 5)", True), ("verifyNumElements(tc, ones(2, 5), 10)", True),
    ("verifyClass(tc, int8(1), 'int8')", True), ("verifyClass(tc, 1, 'single')", False), ("verifyInstanceOf(tc, SampleTest, 'matlab.unittest.TestCase')", True),
    ("verifyGreaterThan(tc, [2 3], 1)", True), ("verifyGreaterThan(tc, [2 3], 2)", False), ("verifyGreaterThanOrEqual(tc, [2 3], 2)", True),
    ("verifyLessThan(tc, [1 2], [2 3])", True), ("verifyLessThanOrEqual(tc, 3, 2)", False), ("verifyReturnsTrue(tc, @() isempty([]))", True),
    ("verifyReturnsTrue(tc, @() 1)", False), ("verifySubstring(tc, 'hello world', 'lo w')", True), ("verifySubstring(tc, \"abc\", \"B\")", False),
    ("verifyMatches(tc, 'abc123', '\\d{3}$')", True), ("verifyMatches(tc, 'abc', '^b')", False), ("verifyFail(tc)", False),
    ("verifySameHandle(tc, h, h)", True), ("verifySameHandle(tc, h, figure('Visible', 'off'))", False), ("verifyNotSameHandle(tc, h, h)", False),
]
for code, want in cases:
    W, out = run(f"tc = matlab.unittest.TestCase.forInteractiveUse; h = figure('Visible', 'off'); {code}")
    passed = 'Verification passed.' in out
    failed = 'Verification failed.' in out
    C(f'{code}: {"passes" if want else "fails"}', passed == want and failed != want, out[-300:])
W, out = run("tc = matlab.unittest.TestCase.forInteractiveUse; try, tc.assertEqual(1, 2), r = 'went on'; catch ex, r = ex.message; end; "
             "try, tc.assumeTrue(false), r2 = 'went on'; catch ex, r2 = ex.message; end; tc.verifyEqual(1, 2, 'my words')")
same('interactive: a failed assertion or assumption is an error; diagnostics shown', (text(W['r']).startswith('Assertion failed'), text(W['r2']).startswith('Assumption failed'), 'my words' in out),
     (True, True, True))
raises("verifyEqual(1, 2)", 'is a method of a test case')
raises("tc = matlab.unittest.TestCase.forInteractiveUse; verifyEqual(tc, 1)", 'Not enough input arguments')
raises("runtests('NoSuchThing')", "no test file, folder or class named 'NoSuchThing'")
raises("runtests('helper')", 'does not give tests')
W, out = run("x = log(exp(2)); tc = matlab.unittest.TestCase.forInteractiveUse; log(tc, 'a note')")
same('log is still the logarithm; with a test case it logs', (W['x'], '[Logged] a note' in out), (2.0, True))
W, out = run("5; t = SampleTest; t.addTeardown(@() 1); b = ans; t.addTeardown(@() 1)")
same('obj.method() of a method that gives nothing leaves ans as it was, and shows nothing', (W.get('b'), 'None' in out), (5.0, False))

# ---- calling Python ---------------------------------------------------------------------------------------------------------------------------
W, out = run("x = py.math.sqrt(2); p = py.math.pi; L = py.list({1, 'two', 3}); cl = class(L); c = cell(L); n = length(L); k = py.len(L); kc = class(k); "
             "d = py.dict(pyargs('a', 1, 'b', 'bee')); s = struct(d); arr = py.numpy.array([1 2 3; 4 5 6]); A = double(arr); ac = class(arr); "
             "v = double(py.numpy.linspace(0, 1, pyargs('num', int32(5)))); u = py.str.upper('abc'); m = py.importlib.import_module('math'); fl = m.floor(2.7); "
             "e = L(2); r = py.functools.reduce(@(a, b) a + b, py.list({1, 2, 3, 4})); z = py.complex(1, 2); none = py.dict().get('q'); b = py.bool(1); "
             "st = string(py.list({'a', 'b'})); ch = char(py.str(42)); i8 = int8(py.list({1.4, 2.6})); lg = logical(py.list({0, 1})); "
             "sz = double(py.numpy.ones(int32(3))); v1 = double(py.numpy.asarray([1; 2; 3]));")
near('py.math.sqrt, py.math.pi', (W['x'], W['p']), (2 ** 0.5, np.pi))
same('py.list: a Python object; cell converts its items', (text(W['cl']), W['c'].a.shape, float(W['c'].a[0, 0]), text(W['c'].a[0, 1])), ('py.list', (1, 3), 1.0, 'two'))
same('a Python int comes back int64; length of a list', (W['n'], int(np.asarray(W['k']).reshape(-1)[0]), text(W['kc'])), (3.0, 3, 'int64'))
same('struct of a dict; pyargs as keywords', (float(W['s'].get1('a')), text(W['s'].get1('b'))), (1.0, 'bee'))
near('a matrix goes as a 2-D array and comes back with double; a vector as 1-D (a row)', (W['A'], W['v'], W['sz'], W['v1']),
     ([[1, 2, 3], [4, 5, 6]], [[0, 0.25, 0.5, 0.75, 1]], [[1, 1, 1]], [[1, 2, 3]]))
same('the class of a NumPy array; a str comes back char', (text(W['ac']), text(W['u'])), ('py.numpy.ndarray', 'ABC'))
same('a method of a module object; p(k) of a list from 1; a function handle as a Python callback', (int(np.asarray(W['fl']).reshape(-1)[0]), text(W['e']), W['r']), (2, 'two', 10.0))
same('complex, None as [], bool as logical', (W['z'], np.asarray(W['none']).shape, W['b']), (complex(1, 2), (0, 0), True))
same('string of a list of str; char of a str; int8 rounds; logical', (texts(W['st']), text(W['ch']), list(np.asarray(W['i8']).reshape(-1)), list(np.asarray(W['lg']).reshape(-1))),
     (['a', 'b'], '42.0', [1, 3], [False, True]))
write('script.py', "import sys\nresult = [len(sys.argv), sys.argv[1]]\ntwice = given * 2\nprint('from the file')\n")
W, out = run("y = pyrun('z = a * 2', 'z', 'a', 21); [q, r] = pyrun([\"import math\", \"q = math.factorial(5)\", \"r = str(q)\"], [\"q\", \"r\"]); "
             "pyrun('kept = 41'); k = pyrun('kept += 1', 'kept'); pyrun(\"print('hello from python')\"); "
             "[res, tw] = pyrunfile('script.py first', [\"result\", \"twice\"], 'given', 4); rc = cell(res); "
             "e = pyenv; mode = e.ExecutionMode; ver = e.Version; st = e.Status;")
same('pyrun: inputs and outputs by name; variables kept from one pyrun to the next', (W['y'], int(np.asarray(W['q']).reshape(-1)[0]), text(W['r']), int(np.asarray(W['k']).reshape(-1)[0])),
     (42.0, 120, '120', 42))
same("Python's printing shows in the Command Window", ('hello from python' in out, 'from the file' in out), (True, True))
same('pyrunfile: sys.argv from the words after the name, inputs and outputs', (int(np.asarray(W['rc'].a[0, 0]).reshape(-1)[0]), text(W['rc'].a[0, 1]), W['tw']), (2, 'first', 8.0))
same('pyenv: in process, loaded, the version', (text(W['mode']), text(W['st']), text(W['ver']) == f'{sys.version_info.major}.{sys.version_info.minor}'), ('InProcess', 'Loaded', True))
raises("py.math.sqrt('x')", 'Python Error: TypeError')
raises("py.nosuchmodule.f(1)", "Python has no module named 'nosuchmodule'")
raises("py.math.nosuchthing(1)", "has no 'nosuchthing'")
raises("pyrun('1/0')", 'ZeroDivisionError')
raises("pyrun('a = 1', 'b')", "no variable 'b'")
raises("pyenv('Version', '3.9')", 'cannot be changed')
raises("double(py.list({'a'}))", 'not numbers')
raises("py.str(table(1))", 'cannot be passed to Python')
W, out = run("L = py.list({1, 2})")
same('a Python object shown with its value', 'Python list with value:' in out and '[1.0, 2.0]' in out, True)

sys.exit(C.done())
