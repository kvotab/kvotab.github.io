"""Symbolic math, run natively (CPython with numpy, scipy and sympy): results
checked by putting them back (solutions into their equations, ODE
solutions into the ODE and its conditions, inverse transforms of
transforms), by numbers (derivatives against differences, integrals
against quadrature, vpa against mpmath's digits), against closed forms,
and the language's side: display, indexing and assignment, symbolic
functions, assumptions, conditions that cannot be decided, conversions,
matlabFunction and plots.

    python3 test_sym.py          (from any folder; needs numpy, scipy and sympy)
"""
import asyncio
import math
import os
import sys

import numpy as np
import mpmath
from scipy import integrate

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char, Cell, Struct, Str  # noqa: E402

R.setup()


def run(code):
    """Run code in a fresh base workspace: (workspace, output)."""
    R.BASE.clear()
    R.BASE.gnames.clear()
    R.take_output()
    asyncio.run(R.execute(code))
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


def same(label, got, want):
    return C(label, got == want, f'got {got!r}, want {want!r}')


def text(v):
    if isinstance(v, Char):
        return v.str()
    if isinstance(v, (bool, float)):
        return v
    return v


def num(code, var='r'):
    """The double value of a result, by double() in the language."""
    W, _ = run(code + f"; zzd = double({var});")
    v = W["zzd"]
    return np.asarray(v, complex if np.iscomplexobj(v) else float)


def shows(code, var):
    """How a variable is shown: char() of it."""
    W, _ = run(code + f"; zzc = char({var});")
    return W["zzc"].str()


def near(label, got, want, tol=1e-9):
    g = np.asarray(got).reshape(-1)
    w = np.asarray(want).reshape(-1)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol)
    return C(label, ok, f'got {g.tolist()}, want {w.tolist()}')


def raises(label, code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = W['e'].str()
    return C(label, words in msg, msg)


# ---- display and the language's syntax ------------------------------------------------------------------------
W, out = run("syms x y\nf = x^2 + 2*x*y + 1")
C('a sym shows in the language: ^ for powers, no Python', 'x^2 + 2*x*y + 1' in out and '**' not in out, out)
same('class and size', (run("syms x; c = class(x^2); s = size([x 1; 2 x]);")[0]['c'].str(), run("syms x; s = size([x 1; 2 x]);")[0]['s'].tolist()), ('sym', [[2.0, 2.0]]))
same('fractions stay exact: sym(1/3) + 1/6', shows("r = sym(1/3) + 1/6", 'r'), '1/2')
same('sym(0.1) is 1/10, sym(pi) is pi, sqrt(2) and -3*pi/4 recognized', [shows(f"r = sym({v})", 'r') for v in ('0.1', 'pi', 'sqrt(2)', '-3*pi/4')],
     ['1/10', 'pi', 'sqrt(2)', '-3*pi/4'])
same('the special numbers in the language: exp(1), Inf, 1i', [shows(f"r = {v}", 'r') for v in ('exp(sym(1))', 'sym(Inf)', 'sym(2) + 3i')], ['exp(1)', 'Inf', '2 + 3i'])
same("sym(0.1, 'f') is the double's own fraction", shows("r = sym(0.1, 'f')", 'r'), '3602879701896397/36028797018963968')
W, out = run("syms x\nA = [x 1; 2 x^2]")
C('a symbolic matrix shows in rows of brackets', '[x,   1]' in out and '[2, x^2]' in out, out)
same('char of a matrix', shows("syms x; r = [x 1; 2 x]", 'r'), '[x, 1; 2, x]')
W, _ = run("syms x y; s = string([x, y^2]);")
same('string of a sym array', list(W['s'].a.reshape(-1)), ['x', 'y^2'])
W, out = run("syms x\nf(x) = x^3")
C('a symbolic function shows as f(x) =', 'f(x) =' in out and 'x^3' in out, out)
W, out = run("syms x y; r = latex(x^2/y);")
same('latex', W['r'].str(), '\\frac{x^{2}}{y}')

# ---- arithmetic, indexing, assignment ----------------------------------------------------------------------------
same('operators: + - * / ^ and their element-wise forms', [shows(f"syms x y; r = {e}", 'r') for e in ('x + x', 'x*y - y*x', 'x/x', '(x^2)^(1/2)', '[x 2].*[3 y]', '[x 2].^2')],
     ['2*x', '0', '1', 'sqrt(x^2)', '[3*x, 2*y]', '[x^2, 4]'])
W, _ = run("syms a b c d; A = [a b; c d]; B = A*A; k = isequal(B(1,1), a^2 + b*c);")
same('matrix product', W['k'], True)
W, _ = run("A = sym([2 1; 1 3]); b = sym([3; 5]); x = A\\b; r = A*x - b;")
same('A\\b solves exactly', shows("A = sym([2 1; 1 3]); b = sym([3; 5]); x = A\\b", 'x'), '[4/5; 7/5]')
same("' conjugates (symbols are complex), .' does not", [shows("syms x; r = [x 1i]'", 'r'), shows("syms x; r = [x 1i].'", 'r')], ['[conj(x); -1i]', '[x; 1i]'])
same('indexing: v(2), v(end), A(2, :)', [shows("syms x y z; v = [x y z]; r = v(2)", 'r'), shows("syms x y z; v = [x y z]; r = v(end)", 'r'),
                                         shows("syms x y; A = [x y; 1 2]; r = A(2, :)", 'r')], ['y', 'z', '[1, 2]'])
same('assignment grows with zeros: v(3) = x', shows("syms x; v = sym([]); v(3) = x", 'v'), '[0, 0, x]')
same('a numeric array takes a symbolic element and becomes sym', shows("syms x; A = zeros(1, 3); A(2) = x", 'A'), '[0, x, 0]')
same('deletion: v(2) = []', shows("syms x y z; v = [x y z]; v(2) = []", 'v'), '[x, z]')
same('concatenation with numbers', shows("syms x; r = [x, 2; 3, x^2]", 'r'), '[x, 2; 3, x^2]')

# ---- symbolic functions ----------------------------------------------------------------------------------------
W, _ = run("syms f(x); f(x) = x^3 - 2*x; a = char(f(2)); b = char(f(sym(1)/2)); c = class(f); d = class(f(2));")
same('f(x) = ... defines a symfun; f(2) its value, a sym', (W['a'].str(), W['b'].str(), W['c'].str(), W['d'].str()), ('4', '-7/8', 'symfun', 'sym'))
same('a symfun at an array of values', shows("syms x; f(x) = x^2; r = f([1 2 3])", 'r'), '[1, 4, 9]')
same('diff of a symfun is a symfun', run("syms x; f(x) = sin(x); g = diff(f); c = class(g);")[0]['c'].str(), 'symfun')
same('argnames and formula', (shows("syms x y; f(x, y) = x*y^2; r = argnames(f)", 'r'), shows("syms x y; f(x, y) = x*y^2; r = formula(f)", 'r')), ('[x, y]', 'x*y^2'))
same('syms f(x, y) with a comma in command syntax', run("syms g(s, t); c = class(g); n = numel(argnames(g));")[0]['n'], 2.0)
same('symfun(formula, inputs)', shows("syms x y; f = symfun(x + y^2, [x y]); r = f(1, 2)", 'r'), '5')

# ---- calculus -------------------------------------------------------------------------------------------------
f = lambda t: t ** 3 * math.sin(t)
W, _ = run("syms x; g = diff(x^3*sin(x), x); h = matlabFunction(g); v = h(1.3);")
near('diff against central differences', W['v'], (f(1.3 + 1e-5) - f(1.3 - 1e-5)) / 2e-5, 1e-7)
same('diff(f, x, 2) and diff(f, 2)', [shows("syms x; r = diff(x^4, x, 2)", 'r'), shows("syms x; r = diff(x^4, 2)", 'r')], ['12*x^2', '12*x^2'])
same('diff picks x: diff(a*x^2)', shows("syms a x; r = diff(a*x^2)", 'r'), '2*a*x')
q, _ = integrate.quad(lambda t: t * math.exp(-t) * math.cos(t), 0, 2)
near('a definite integral against quadrature', num("syms x; r = int(x*exp(-x)*cos(x), 0, 2)"), q, 1e-10)
W, _ = run("syms x; F = int(1/(1 + x^2), x); r = diff(F, x) - 1/(1 + x^2); k = isequal(simplify(r), sym(0));")
same('an indefinite integral differentiates back', W['k'], True)
near('int to Inf', num("syms x; r = int(exp(-x^2), -Inf, Inf)"), math.sqrt(math.pi))
C('an integral with no closed form stays int(...)', 'int(' in shows("syms x; r = int(sin(sin(x)), x)", 'r'), shows("syms x; r = int(sin(sin(x)), x)", 'r'))
same("int(..., 'Hold', true)", shows("syms x; r = int(x^2, x, 'Hold', true)", 'r'), 'int(x^2, x)')
same('limits: two-sided, one-sided, at Inf, disagreeing sides', [shows(f"syms x; r = {e}", 'r') for e in ("limit(sin(x)/x, x, 0)", "limit(1/x, x, 0, 'right')",
                                                                                         "limit(1/x, x, 0, 'left')", "limit((1 + 1/x)^x, x, Inf)", "limit(1/x, x, 0)")],
     ['1', 'Inf', '-Inf', 'exp(1)', 'NaN'])
W, _ = run("syms x; t = taylor(exp(x)); c = sym2poly(t);")
near('taylor(exp(x)): 1/k! up to x^5', W['c'], [1 / math.factorial(k) for k in range(5, -1, -1)], 1e-15)
W, _ = run("syms x; t = taylor(log(x), x, 1, 'Order', 4); c = sym2poly(expand(t));")
near("taylor about 1 with 'Order' 4", W['c'], np.polyfit(np.linspace(0.5, 1.5, 9), [(u - 1) - (u - 1) ** 2 / 2 + (u - 1) ** 3 / 3 for u in np.linspace(0.5, 1.5, 9)], 3), 1e-12)
same('symsum: finite and infinite', [shows("syms k; r = symsum(k^2, k, 1, 10)", 'r'), shows("syms k; r = symsum(1/k^2, k, 1, Inf)", 'r')], ['385', 'pi^2/6'])
same('symprod', shows("syms k; r = symprod(k, k, 1, 6)", 'r'), '720')
same('jacobian and hessian', [shows("syms x y; r = jacobian([x*y, x + y], [x, y])", 'r'), shows("syms x y; r = hessian(x^2*y, [x, y])", 'r')],
     ['[y, x; 1, 1]', '[2*y, 2*x; 2*x, 0]'])
same('gradient, divergence, curl, laplacian', [shows(f"syms x y z; r = {e}", 'r') for e in ("gradient(x^2*y, [x, y])", "divergence([x*y, y*z, z*x], [x y z])",
                                                                                          "curl([y, -x, 0], [x y z])", "laplacian(x^2 + y^2, [x y])")],
     ['[2*x*y; x^2]', 'x + y + z', '[0; 0; -2]', '4'])

# ---- algebra --------------------------------------------------------------------------------------------------
same('simplify', [shows(f"syms x; r = simplify({e})", 'r') for e in ('sin(x)^2 + cos(x)^2', '(x^2 - 1)/(x - 1)')], ['1', 'x + 1'])
same('expand, with trig', [shows("syms x; r = expand((x + 1)^3)", 'r'), shows("syms x y; r = expand(sin(x + y))", 'r')],
     ['x^3 + 3*x^2 + 3*x + 1', 'sin(x)*cos(y) + sin(y)*cos(x)'])
same('factor: a polynomial and an integer give their factors', [shows("syms x; r = factor(x^3 - x)", 'r'), shows("r = factor(sym(360))", 'r')],
     ['[x - 1, x, x + 1]', '[2, 2, 2, 3, 3, 5]'])
same('factor of numbers is still the numeric one', run("r = factor(12);")[0]['r'].tolist(), [[2.0, 2.0, 3.0]])
same('collect, horner, partfrac', [shows("syms x y; r = collect((x + y)*(x - 1), x)", 'r'), shows("syms x; r = horner(x^3 - 2*x^2 + 3*x - 4)", 'r'),
                                   shows("syms x; r = partfrac(1/(x^2 - 1), x)", 'r')],
     ['x^2 + x*(y - 1) - y', 'x*(x*(x - 2) + 3) - 4', '-1/(2*(x + 1)) + 1/(2*(x - 1))'])
W, _ = run("syms x y; [n, d] = numden(x/y + y/x); a = char(n); b = char(d);")
same('numden', (W['a'].str(), W['b'].str()), ('x^2 + y^2', 'x*y'))
W, _ = run("syms x; [c, t] = coeffs(16*x^2 + 19*x + 11); a = char(c); b = char(t); c2 = char(coeffs(16*x^2 + 11, 'All'));")
same('coeffs: lowest power first, with their terms; all from the highest with All', (W['a'].str(), W['b'].str(), W['c2'].str()),
     ('[11, 19, 16]', '[1, x, x^2]', '[16, 0, 11]'))
same('poly2sym and sym2poly', (shows("r = poly2sym([1 -2 3])", 'r'), run("syms x; r = sym2poly(x^3 - 2*x + 5);")[0]['r'].tolist()), ('x^2 - 2*x + 3', [[1.0, 0.0, -2.0, 5.0]]))
same("rewrite(tan(x), 'sincos')", shows("syms x; r = rewrite(tan(x), 'sincos')", 'r'), 'sin(x)/cos(x)')
near("rewrite(sin(x), 'exp') is still sin(x)", num("syms x; r = subs(rewrite(sin(x), 'exp'), x, 0.7)"), math.sin(0.7), 1e-15)
same('subs: a value, an array of values, several at once, by cells', [shows(f"syms x y; r = {e}", 'r') for e in
                                                                       ("subs(x^2 + 1, x, 3)", "subs(x^2, x, [1 2 3])", "subs(x + y, [x y], [1 2])", "subs(x*y, {x, y}, {2, x})")],
     ['10', '[1, 4, 9]', '3', '2*x'])
same('subs(f) takes values from the workspace', shows("syms x a; f = a*x^2; a = 3; r = subs(f)", 'r'), '3*x^2')
same('children, lhs, rhs, has', (run("syms x y; c = children(x + y); n = numel(c); k = class(c);")[0]['n'], shows("syms x; r = lhs(x^2 == 4)", 'r'),
                                 shows("syms x; r = rhs(x^2 == 4)", 'r'), run("syms x y; h = has(x^2 + y, y);")[0]['h']), (2.0, 'x^2', '4', True))
same('isolate and finverse', (shows("syms x y; r = isolate(2*x + y == 4, x)", 'r'), shows("syms x; r = finverse(exp(2*x))", 'r')), ('x == 2 - y/2', 'log(x)/2'))
same('compose', shows("syms x y; r = compose(sin(x), y^2)", 'r'), 'sin(y^2)')

# ---- equations ---------------------------------------------------------------------------------------------------
same('solve: a quadratic, as a column', shows("syms x; r = solve(x^2 - 3*x + 2 == 0, x)", 'r'), '[1; 2]')
W, _ = run("syms a b c x; s = solve(a*x^2 + b*x + c == 0, x); r = simplify(subs(a*x^2 + b*x + c, x, s)); k = isequal(r, sym([0; 0]));")
same('solve: the general quadratic, put back', W['k'], True)
W, _ = run("syms x y; [u, v] = solve([x + y == 3, x - y == 1], [x, y]); S = solve([x + y == 3, x - y == 1], [x, y]); f = fieldnames(S); a = char(u); b = char(S.y);")
same('solve: a system, as outputs and as a struct', (W['a'].str(), W['b'].str(), list(x.str() for x in W['f'].a.reshape(-1))), ('2', '1', ['x', 'y']))
same('solve keeps solutions that agree with assumptions', [shows("syms x; assume(x > 0); r = solve(x^2 == 4, x)", 'r'), shows("syms x; assume(x, 'clear'); r = solve(x^2 == 4, x)", 'r')],
     ['2', '[-2; 2]'])
same("solve with 'Real', true", shows("syms x; r = solve(x^3 == 1, x, 'Real', true)", 'r'), '1')
W, _ = run("syms x; S = solve(sin(x) == 0, x, 'ReturnConditions', true); p = char(S.parameters); c = char(S.conditions(1));")
same("solve with 'ReturnConditions': a family in k", (W['p'].str(), W['c'].str()), ('k', "in(k, 'integer')"))
W, _ = run("syms x; r = vpasolve(x^3 - x - 1 == 0, x); d = double(r);")
real = np.asarray(W['d']).reshape(-1)
near('vpasolve: every root of a polynomial', np.sort_complex(real), np.sort_complex(np.roots([1, 0, -1, -1])), 1e-12)
near('vpasolve from a start', num("syms x; r = vpasolve(cos(x) == x, x, 1)"), 0.7390851332151607, 1e-14)
near('vpasolve within a range', num("syms x; r = vpasolve(sin(x) == 0.5, x, [2 3])"), math.pi - math.asin(0.5), 1e-14)

# ---- differential equations ------------------------------------------------------------------------------------------
W, _ = run("syms y(t) a; s = dsolve(diff(y, t) == a*y, y(0) == 5); r = simplify(diff(s, t) - a*s); k = isequal(r, sym(0)); v = char(s);")
same('dsolve: a first-order ODE and its condition; the answer satisfies both', (W['k'], W['v'].str()), (True, '5*exp(a*t)'))
W, _ = run("syms z(t); Dz = diff(z, t); s = dsolve(diff(z, t, 2) == -z, [z(0) == 0, Dz(0) == 1]); v = char(s);")
same('dsolve: second order with a condition on the derivative', W['v'].str(), 'sin(t)')
W, _ = run("syms u(t) v(t); S = dsolve([diff(u, t) == v, diff(v, t) == -u], [u(0) == 1, v(0) == 0]); a = char(S.u); b = char(S.v);")
same('dsolve: a system, as a struct', (W['a'].str(), W['b'].str()), ('cos(t)', '-sin(t)'))
same('dsolve: free constants C1, C2', 'C1' in shows("syms y(t); r = dsolve(diff(y, t, 2) == y)", 'r'), True)

# ---- transforms ---------------------------------------------------------------------------------------------------------
same('laplace and ilaplace', [shows("syms t; r = laplace(t^2*exp(-t))", 'r'), shows("syms s; r = ilaplace(1/(s^2 + 1))", 'r'),
                               shows("syms t; r = laplace(t*sin(2*t))", 'r')], ['2/(s + 1)^3', 'sin(t)', '4*s/(s^2 + 4)^2'])
W, _ = run("syms t; f = t*sin(2*t); g = ilaplace(laplace(f)); k = isequal(simplify(g - f), sym(0));")
same('ilaplace undoes laplace', W['k'], True)
same('fourier of a Gaussian, with exp(-1i*w*x)', shows("syms x; r = fourier(exp(-x^2))", 'r'), 'sqrt(pi)*exp(-w^2/4)')
W, _ = run("syms w x; r = ifourier(sqrt(sym(pi))*exp(-w^2/4)); k = isequal(simplify(r - exp(-x^2)), sym(0));")
same('ifourier undoes it', W['k'], True)
same('ztrans and iztrans', [shows("syms n; r = ztrans(2^n)", 'r'), shows("syms z; r = iztrans(z/(z - 2))", 'r')], ['z/(z - 2)', '2^n'])
W, _ = run("syms n z; F = ztrans(n*3^n); f = iztrans(F); k = isequal(simplify(f - n*3^n), sym(0));")
same('iztrans undoes ztrans for a double pole', W['k'], True)

# ---- numbers and digits ---------------------------------------------------------------------------------------------------
W, _ = run("v = vpa(pi, 50); c = char(v);")
mpmath.mp.dps = 60
same('vpa(pi, 50) is pi to 50 significant digits', W['c'].str()[:51], mpmath.nstr(mpmath.pi, 50)[:51])
mpmath.mp.dps = 15
W, _ = run("old = digits(20); v = vpa(sqrt(sym(2))); c = char(v); digits(old);")
same('digits sets vpa\'s digits', len(W['c'].str().replace('.', '')), 20)
near('double', num("r = sqrt(sym(2)) + 1"), math.sqrt(2) + 1, 1e-15)
raises('double of an expression with variables says so', "syms x; double(x + 1)", 'Unable to convert expression containing symbolic variables')
same('logical and isAlways', (run("r = logical(sym(2) > 1);")[0]['r'], run("syms w real; r = isAlways(w^2 >= 0);")[0]['r']), (True, True))
W, out = run("syms x; r = isAlways(x^2 >= 0);")
same('isAlways of what cannot be decided: false, with a warning', (W['r'], 'Unable to prove' in out), (False, True))
raises('if on a condition that cannot be decided says so', "syms x; if x > 0, disp(1), end", 'Unable to prove')
same('if on a decidable condition', run("syms x; r = 0; if x == x, r = 1; end")[0]['r'], 1.0)
same('isequal compares mathematically and with numbers', (run("syms x; r = isequal(x + x, 2*x);")[0]['r'], run("r = isequal(sym(1/2), 0.5);")[0]['r'],
                                                           run("syms x; r = isequal(x, x + 1);")[0]['r']), (True, True, False))
same('assumptions', [shows("syms x; assume(x > 0); r = assumptions(x)", 'r'), shows("syms k integer; r = assumptions(k)", 'r')], ['x > 0', "in(k, 'integer')"])
run("syms x clear; syms k clear;")

# ---- functions of numbers, plots ----------------------------------------------------------------------------------------------
W, _ = run("syms x y; f = matlabFunction(x^2 + sin(y)); v = f([1 2], [0 pi/2]); t = func2str(f);")
near('matlabFunction: element-wise, takes arrays', W['v'], [1, 5], 1e-15)
same("its inputs in symvar's order", W['t'].str(), '@(x,y)x.^2+sin(y)')
W, _ = run("syms x y; f = matlabFunction(x - y, 'Vars', [y x]); v = f(1, 10);")
same("matlabFunction 'Vars' sets the order", W['v'], 9.0)
W, _ = run("syms x; f = matlabFunction([x, x^2; 1, 2*x]); v = f(3);")
same('matlabFunction of a matrix', W['v'].tolist(), [[3.0, 9.0], [1.0, 6.0]])
W, _ = run("close all force; syms x; fplot(sin(x), [0 2*pi]); n = numel(get(gca, 'Children')); close all force;")
same('fplot of a symbolic expression', W['n'], 1.0)
W, _ = run("close all force; syms x y; fimplicit(x^2 + y^2 == 1, [-2 2]); n = numel(get(gca, 'Children')); k = get(get(gca, 'Children'), 'Type'); close all force;")
same('fimplicit draws the zero contour', (W['n'], W['k'].str()), (1.0, 'contour'))
W, _ = run("close all force; syms t; fplot3(cos(t), sin(t), t, [0 4*pi]); n = numel(get(gca, 'Children')); close all force;")
same('fplot3', W['n'], 1.0)
near('heaviside, dirac, sinc, kroneckerDelta for numbers', np.concatenate([np.asarray(run("r = heaviside([-1 0 2]);")[0]['r']).reshape(-1),
                                                                         np.asarray(run("r = sinc([0 0.5]);")[0]['r']).reshape(-1),
                                                                         np.asarray(run("r = kroneckerDelta([1 2], 2);")[0]['r']).reshape(-1)]),
     [0, 0.5, 1, 1, 2 / math.pi, 0, 1])
near('lambertw for numbers', run("r = lambertw(1);")[0]['r'], 0.5671432904097838, 1e-15)
same('heaviside of a sym is symbolic, 1/2 at 0', shows("r = heaviside(sym(0))", 'r'), '1/2')
same('piecewise', shows("syms x; r = piecewise(x < 0, -x, x)", 'r'), 'piecewise(x < 0, -x, x)')
same('str2sym', [shows("r = str2sym('x^2 + sin(y)')", 'r'), shows("r = str2sym('2*x == 3')", 'r')], ['x^2 + sin(y)', '2*x == 3'])
same("sym('a', [1 3]) and syms with a size", [shows("r = sym('a', [1 3])", 'r'), shows("syms q [2 2]; r = q", 'r')], ['[a1, a2, a3]', '[q1_1, q1_2; q2_1, q2_2]'])
same('eig of a symbolic matrix', shows("r = eig(sym([2 0; 0 3]))", 'r'), '[2; 3]')
W, _ = run("syms a; A = [a 1; 1 a]; [V, D] = eig(A); k = isequal(simplify(A*V - V*D), sym(zeros(2)));")
same('[V, D] = eig(A): A*V = V*D', W['k'], True)
W, _ = run("A = sym(magic(3)); k = isequal(inv(A)*A, sym(eye(3))); d = char(det(A)); r = rank(A);")
same('inv, det, rank', (W['k'], W['d'].str(), W['r']), (True, '-360', 3.0))

# chained comparisons: 0 < x < 1 is 0 < x & x < 1, in assume, piecewise and str2sym
same('a chained comparison is a conjunction', [shows("syms x y; r = 0 < x < 1", 'r'), shows("syms x y; r = 1 > x >= y", 'r'),
                                               shows("r = str2sym('0 < y < 1')", 'r')],
     ['0 < x & x < 1', '1 > x & x >= y', '0 < y & y < 1'])
same('assume of a chain replaces, splits it, and lists each relation once',
     shows("syms u u_c u_r u_f k P_er positive real; assume(0 < u_c < u_r < u_f); r = assumptions([u u_c u_r u_f k P_er])", 'r'),
     '[u > 0, u_c > 0, u_c < u_r, u_r < u_f, k > 0, P_er > 0]')
same('a relation goes with a variable assumed anew', [shows("syms a b; assume(a < b); assume(a > 0); r = assumptions([a b])", 'r'),
                                                     shows("syms a b; assume(0 < a < b); syms a positive; r = assumptions(b)", 'r')],
     ['a > 0', '[]'])
same('assume of an or, of one variable and of two', [shows("syms x y; assume(x < -1 | x > 1); r = assumptions(x)", 'r'),
                                                    shows("syms x y; assume(x > 0 | y > 0); r = assumptions([x y])", 'r')],
     ['x > 1 | x < -1', 'x > 0 | y > 0'])
raises('assume refuses what is no condition, keeping what was assumed', "syms x positive; assume(x)", 'takes a condition')
same('... and keeps what was assumed', shows("syms x positive; try, assume(x), end; r = assumptions(x)", 'r'), 'x > 0')
same('solve filters by a relation kept beside the symbol', shows("syms x; assume(x > 2); r = solve(x^2 == 9, x)", 'r'), '3')
PW = ("syms C_1 C_2; syms u u_c u_r u_f k P_er positive real; assume(0 < u_c < u_r < u_f); "
      "Pe(u) = piecewise(u < u_c, 0, u_c <= u <= u_r, C_1 + C_2*u^k, u_r < u <= u_f, P_er, u_f < u, 0);")
same('piecewise keeps chained conditions as written', shows(PW + " r = Pe", 'r'),
     'piecewise(u < u_c, 0, u_c <= u & u <= u_r, C_1 + C_2*u^k, u_r < u & u <= u_f, P_er, u_f < u, 0)')
W, _ = run(PW + " g = subs(Pe, [u_c u_r u_f C_1 C_2 k P_er], [1 2 3 0 1 2 5]); r = double(subs(g, u, [0.5 1 1.5 2 2.5 3 3.5]));")
near('piecewise with chained conditions, at numbers', W['r'], [[0, 1, 2.25, 4, 5, 5, 0]], 0)
same('piecewise without otherwise shows no NaN', shows("syms x; r = piecewise(x < 0, -1, x > 0, 1)", 'r'), 'piecewise(x < 0, -1, x > 0, 1)')
near('piecewise on numbers picks element by element', run("r = piecewise([1 0 0] == 1, 5, [0 1 0] == 1, [7 8 9]); r(isnan(r)) = -1;")[0]['r'], [[5, 8, -1]], 0)
W, _ = run("close all force; syms x; fplot(piecewise(x < -1, -1, -1 <= x <= 1, x, 1 < x, 1), [-2 2]); h = get(gca, 'Children'); "
           "r = [min(h.YData) max(h.YData)]; close all force;")
near('fplot of a piecewise expression', W['r'], [[-1, 1]], 1e-12)

# the relations assumed settle piecewise conditions: a call, subs, simplify, isAlways; then solve
same('a call settles piecewise conditions by the relations assumed',
     [shows(PW + " r = Pe(u_c)", 'r'), shows(PW + " r = Pe(u_r)", 'r'), shows(PW + " r = subs(Pe, u, u_f)", 'r'), shows(PW + " r = simplify(Pe(u_f))", 'r')],
     ['C_1 + C_2*u_c^k', 'C_1 + C_2*u_r^k', 'P_er', 'P_er'])
W, _ = run(PW + " sol = solve([Pe(u_c) == 0; Pe(u_r) == P_er], [C_1 C_2]); "
                "k1 = isAlways(simplify(subs(C_1 + C_2*u_c^k, [C_1 C_2], [sol.C_1 sol.C_2])) == 0); "
                "k2 = isAlways(simplify(subs(C_1 + C_2*u_r^k, [C_1 C_2], [sol.C_1 sol.C_2]) - P_er) == 0); "
                "a1 = isAlways(u_c < u_f); a2 = isAlways(u_f <= u_c);")
same('solve through the settled calls, and isAlways by the relations', (W['k1'], W['k2'], W['a1'], W['a2']), (True, True, True, False))

# syms makes variables even of function names; subs keeps a symbolic function; isolate an expression
W, out = run("syms x(t) m c k F(t)\neq = m*diff(x,t,t) + c*diff(x,t) + k*x == F;\nsyms gamma omega_0\n"
             "eq = subs(eq,[c k],[m*gamma m*omega_0^2])\nz = char(2*gamma);")
same('syms gamma is a variable in the same code', W['z'].str(), '2*gamma')
C('subs keeps a symbolic function', 'eq(t) =' in out and 'gamma*m*diff(x(t), t) + m*omega_0^2*x(t) + m*diff(x(t), t, 2) == F(t)' in out, out)
same('isolate a derivative, an expression', [shows("syms m a g theta(t) r; eqn = subs(m*a == -m*g*sin(theta), a, r*diff(theta,2)); r = isolate(eqn, diff(theta,2))", 'r'),
                                             shows("syms x y; r = isolate(x^2 + sin(y) == 3, sin(y))", 'r')],
     ['diff(theta(t), t, 2) == -g*sin(theta(t))/r', 'sin(y) == 3 - x^2'])
raises('isolate refuses a number', "syms x; isolate(x == 1, 2)", 'isolate takes a variable or an expression')

# equations: operators and functions work on each side
EQ = "syms x y m a; e = m*x + m*y == a*m;"
same('operators on an equation work on each side', [shows(EQ + " r = e/m", 'r'), shows(EQ + " r = 2*e", 'r'), shows(EQ + " r = e + 1", 'r'),
                                                    shows(EQ + " r = -e", 'r'), shows(EQ + " r = e - e", 'r'), shows("syms x y; r = (x < y) + 1", 'r')],
     ['(m*x + m*y)/m == a', '2*m*x + 2*m*y == 2*a*m', 'm*x + m*y + 1 == a*m + 1', '-m*x - m*y == -a*m', '0 == 0', 'x + 1 < y + 1'])
same('functions of an equation work on each side', [shows(EQ + " r = collect(e, m)", 'r'), shows(EQ + " r = log(e)", 'r'),
                                                    shows("syms x m; r = diff(x^2 == m*x, x)", 'r'), shows("syms x m; r = int(x == m, x)", 'r')],
     ['m*(x + y) == a*m', 'log(m*x + m*y) == log(a*m)', '2*x == m', 'x^2/2 == m*x'])
GM = ("syms x(t) m c k F(t)\neq = m*diff(x,t,t) + c*diff(x,t) + k*x == F;\nsyms gamma omega_0\n"
      "eq = subs(eq,[c k],[m*gamma m*omega_0^2]);\neq = collect(eq,m)/m\n")
W, out = run(GM)
C('collect(eq, m)/m of a symbolic function', 'eq(t) =' in out and 'gamma*diff(x(t), t) + omega_0^2*x(t) + diff(x(t), t, 2) == F(t)/m' in out, out)
same('collect, combine, partfrac, simplifyFraction and rewrite keep a symbolic function',
     [run("syms m t; syms f(t); f(t) = m*t + m*t^2 + 1/(t^2-1); r = " + c + "; n = numel(argnames(r));")[0]['n']
      for c in ("collect(f, m)", "combine(f)", "partfrac(f, t)", "simplifyFraction(f)", "rewrite(sin(t)*f, 'exp')")], [1.0] * 5)
W, out = run(GM + "syms X s\neqL = laplace(eq);\neqL = subs(eqL, laplace(x(t), t, s), X);\n"
                  "eqL = subs(eqL, [x(0) subs(diff(x(t), t), t, 0)], [0 0]);\nXs = solve(eqL, X); r = char(Xs); q = char(laplace(diff(x, t)));")
same('laplace of an equation, its initial values replaced, solved', (W['r'].str(), W['q'].str()),
     ('laplace(F(t), t, s)/(gamma*m*s + m*omega_0^2 + m*s^2)', 's*laplace(x(t), t, s) - x(0)'))

# plots: symbolic numbers drawn as doubles; fpolarplot
W, _ = run("close all force; syms x y; u = sin(x^2 + y^2); v = cos(x*y); [X,Y] = meshgrid(-1:.1:1,-1:.1:1); "
           "U = subs(u,[x y],{X,Y}); V = subs(v,[x y],{X,Y}); quiver(X,Y,U,V); h = get(gca, 'Children'); c = class(h.UData); "
           "d = max(abs([h.UData(:) - sin(X(:).^2 + Y(:).^2); h.VData(:) - cos(X(:).*Y(:))])); close all force;")
C('quiver of symbolic numbers draws their values', W['c'].str() == 'double' and W['d'] < 1e-15, (W['c'].str(), W['d']))
W, _ = run("close all force; syms t; fpolarplot(sin(6*t)); h = get(gca, 'Children'); n = numel(h.YData); "
           "m = max(abs(h.YData - sin(6*h.XData))); lim = [min(h.XData) max(h.XData)]; close all force;")
near('fpolarplot of an expression: r = f(theta) over [0 2*pi]', [W['n'], W['m']] + list(np.asarray(W['lim']).reshape(-1)), [1000, 0, 0, 2 * math.pi], 1e-12)
W, _ = run("close all force; p = fpolarplot(@(th) 1 + cos(th), [0 pi], 'r--', 'LineWidth', 2); w = p.LineWidth; c = p.Color; "
           "lim = [min(p.XData) max(p.XData)]; close all force;")
near('fpolarplot of a handle over an interval, with a line spec and width', [W['w']] + list(np.asarray(W['c']).reshape(-1)) + list(np.asarray(W['lim']).reshape(-1)),
     [2, 1, 0, 0, 0, math.pi], 1e-12)
raises('fpolarplot refuses an interval that does not increase', "fpolarplot(@(th) th, [1 0])", 'increasing')

sys.exit(C.done())
