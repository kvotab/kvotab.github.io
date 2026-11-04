"""Problem-based optimization, run natively (CPython with numpy and scipy):
optimvar, expressions and constraints (their text, values and
coefficients), optimproblem and eqnproblem solved by the solver each
calls for, checked against the same problems given to linprog,
intlinprog and quadprog as matrices, against brute force and against
SciPy; fcn2optimexpr, prob2struct, varindex, show, infeasibility; and
paretosearch on fronts whose shape is known.

    python3 test_optimprob.py          (from any folder)
"""
import asyncio
import itertools
import os
import sys
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

R.setup()
warnings.filterwarnings('ignore')

from plab.builtins import optimprob as P  # noqa: E402


def run(code):
    R.BASE.clear()
    R.take_output()
    asyncio.run(R.execute(code))
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


def near(label, got, want, tol=1e-10):
    g, w = a(got), a(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {np.round(g, 8).tolist() if g.size < 30 else g.shape}, want {np.round(w, 8).tolist() if w.size < 30 else w.shape}')


def text(v):
    return v.str() if isinstance(v, Char) else str(v)


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = text(W['e'])
    return C(f'refused: {code}', words in msg, msg)


def field(s, name):
    return s.get1(name)


QUIET = "optimoptions('linprog', 'Display', 'off')"

# ---- variables -------------------------------------------------------------------------------------------------------

W, outp = run("x = optimvar('x', 2, 3, 'Type', 'integer', 'LowerBound', 0, 'UpperBound', 5); n = x.Name; t = x.Type; lb = x.LowerBound; sz = size(x);"
              "y = optimvar('y', {'a', 'b', 'c'}, 'LowerBound', [1 2 3]); ylb = y.LowerBound; names = y.IndexNames; k = numel(y);"
              "x.UpperBound = 4; ub = x.UpperBound; c = class(x);")
C('optimvar: name, type, size', text(W['n']) == 'x' and text(W['t']) == 'integer' and a(W['sz']).reshape(-1).tolist() == [2, 3], (text(W['n']), text(W['t']), W['sz']))
near('optimvar: a scalar bound fills the array', W['lb'], np.zeros((2, 3)))
near('optimvar: names make a dimension; a row of bounds fits a column variable', W['ylb'], [[1], [2], [3]])
C('optimvar: IndexNames', [text(c) for c in W['names'].a[0, 0].a.reshape(-1)] == ['a', 'b', 'c'] and W['names'].a[0, 1].a.size == 0, W['names'])
near('optimvar: bounds set afterwards', W['ub'], np.full((2, 3), 4.0))
C('optimvar: its class', text(W['c']) == 'optim.problemdef.OptimizationVariable', text(W['c']))
W, _ = run("x = optimvar('x', 3); p = optimproblem('Objective', sum(x)); x.LowerBound = 2; v = p.Variables.x.LowerBound;")
near('optimvar is a handle: bounds set later reach the problem', W['v'], [[2], [2], [2]])

# ---- expressions and their text --------------------------------------------------------------------------------------------

_, o = run("x = optimvar('x', 3); e = 3*x(1)^2 + x(1)*x(2) - 2*x(3) + 5")
C('a quadratic expression written term by term', 'Quadratic OptimizationExpression' in o and '3*x(1)^2 + x(1)*x(2) - 2*x(3) + 5' in o, o)
_, o = run("x = optimvar('x', 2); y = optimvar('y'); e = [1 2; 3 4]*x - y")
C('a linear expression array, element by element', '(1) x(1) + 2*x(2) - y' in o and '(2) 3*x(1) + 4*x(2) - y' in o, o)
_, o = run("s = optimvar('s', {'A', 'B'}, {'p', 'q'}); e = s('B', 'q') + 2*s(1, 2)")
C('index names in the text and as indices', "s('A', 'q')" in o and "s('B', 'q')" in o and '2*' in o, o)
_, o = run("m = optimvar('m', 2, 2); e = m + 1")
C('a matrix of expressions numbered by subscripts', '(2, 1) m(2, 1) + 1' in o, o)
W, _ = run("x = optimvar('x', 3); e = optimexpr(3); for k = 1:3, e(k) = k*x(k) - 1; end; v = evaluate(e, struct('x', [1; 2; 3]));"
           "w = evaluate(sum(x.^2) + x(1)*x(3), struct('x', [1 2 3])); c = class(e); sz = size(optimexpr(2, 4));")
near('optimexpr filled element by element, evaluated', W['v'], [[0], [3], [8]])
near('evaluate: a quadratic at a point', W['w'], 17.0)
C('optimexpr: its class and size', text(W['c']) == 'optim.problemdef.OptimizationExpression' and a(W['sz']).reshape(-1).tolist() == [2, 4], (W['c'], W['sz']))
W, _ = run("x = optimvar('x', 2, 3); e = sum(x, 2); f = sum(x(:)); g = cumsum(x, 2); h = x'; i = [x; 2*x]; v = evaluate(e, struct('x', [1 2 3; 4 5 6]));"
           "vg = evaluate(g, struct('x', [1 2 3; 4 5 6])); vh = evaluate(h, struct('x', [1 2 3; 4 5 6])); vi = evaluate(i(3:4, 2), struct('x', [1 2 3; 4 5 6]));"
           "vn = evaluate(norm(x(:, 1)), struct('x', [3 0 0; 4 0 0])); vd = evaluate(dot(x(1, :), [1 1 1]), struct('x', [1 2 3; 4 5 6]));")
near('sum along a dimension', W['v'], [[6], [15]])
near('cumsum along a dimension', W['vg'], [[1, 3, 6], [4, 9, 15]])
near('transpose', W['vh'], [[1, 4], [2, 5], [3, 6]])
near('concatenation and indexing', W['vi'], [[4], [10]])
near('norm of a vector', W['vn'], 5.0)
near('dot', W['vd'], 6.0)


def forms_agree(code):
    """The sparse forms against the expression's own values at random points."""
    W, o = run("x = optimvar('x', 3); y = optimvar('y', 2); M = optimvar('M', 2, 2); A = magic(3); " + code)
    node = W['e'].node
    L = P.Layout(node.vars({}).values())
    X = np.random.default_rng(7).standard_normal((L.n, 6))
    vals = P._eval_flat(node, L, X)
    f = P._form(node, L, {})
    for k in range(vals.shape[0]):
        H, g, c = P._quad_parts(f, k, L.n)
        q = np.array([0.5 * X[:, j] @ (H @ X[:, j]) + g @ X[:, j] + c for j in range(X.shape[1])])
        if not np.allclose(q, vals[k], rtol=1e-12, atol=1e-12):
            return False
    return True


for code in ["e = 3*x - [1; 2; 3];", "e = A*x + 2;", "e = x'*A;", "e = sum(A(:, 1:2) .* (x*y'), 2);", "e = sum(x.^2) - 2*x(1)*x(3) + y(2)/4;",
             "e = x'*A*x + [1 2 3]*x;", "e = cumsum([x; y]);", "e = [x(1:2)', y'; y', 5, 6];", "e = sum(M, 1) - sum(M(:));", "e = M';",
             "e = (x(1) - y(2)).^2 + (M(2, 1) + 3)^2;", "e = dot(x, A*x);", "e = optimexpr(3, 1); for k = 1:3, e(k) = k*x(k)^2 - y(1); end",
             "e = -x' * (A' * x) / 2;", "e = x(2)*(x(1) + y(1)) - 4;", "e = reshape(M, 4, 1) .* [1; 2; 3; 4];"]:
    C(f'coefficients from the forms equal the values: {code}', forms_agree(code))
W, _ = run("x = optimvar('x', 3); e = x'*[2 1 0; 1 3 1; 0 1 4]*x - [1 2 3]*x;")
H, g, c = P._quadratic(W['e'].node, P.Layout(W['e'].node.vars({}).values()))
near('a quadratic form: H is twice the symmetric matrix', H, [[4, 2, 0], [2, 6, 2], [0, 2, 8]])
near('a quadratic form: the linear part', g, [-1, -2, -3])

# ---- constraints ---------------------------------------------------------------------------------------------------------

_, o = run("x = optimvar('x', 2); y = optimvar('y'); c = x(1) + x(2) + y - 4 <= 0, d = x(1) - x(2) >= -1")
C('constraints written with the constant on the right', 'x(1) + x(2) + y <= 4' in o and 'x(1) - x(2) >= -1' in o and 'OptimizationInequality' in o, o)
W, o = run("w = optimvar('w', 4); c = optimconstr(3); for k = 1:3, c(k) = w(k) + w(k+1) <= k; end; c, v = infeasibility(c, struct('w', [1 1 1 1]));"
           "e = optimeq(2); e(1) = w(1) == 1; e(2) = sum(w) == 2; ce = class(e); u = infeasibility(e, struct('w', [3 0 0 0]));"
           "q = infeasibility(w >= [0; 1; 2; 3], struct('w', [1 1 1 1])); part = c(2:3); sp = size(part);")
C('optimconstr filled in a loop', '(3) w(3) + w(4) <= 3' in o, o)
near('infeasibility of <=', W['v'], [[1], [0], [0]])
near('infeasibility of ==', W['u'], [[2], [1]])
near('infeasibility of >=', W['q'], [[0], [0], [1], [2]])
C('optimeq holds equalities', text(W['ce']) == 'optim.problemdef.OptimizationEquality', W['ce'])
near('constraints indexed', W['sp'], [[2, 1]])
raises("w = optimvar('w', 2); c = optimineq(2); c(1) = w(1) == 1", 'inequalities only')
raises("w = optimvar('w', 2); c = optimeq(2); c(1) = w(1) <= 1", 'equalities only')
raises("w = optimvar('w', 2); c = w ~= 1", 'not a constraint')

# ---- linear problems -----------------------------------------------------------------------------------------------------

W, o = run(f"""rng(3); m = 12; n = 15; Cst = rand(m, n); s = 50 + 50*rand(m, 1); d = rand(1, n); d = d / sum(d) * sum(s) * 0.9;
X = optimvar('X', m, n, 'LowerBound', 0);
p = optimproblem('Objective', sum(sum(Cst .* X)));
p.Constraints.sup = sum(X, 2) <= s;
p.Constraints.dem = sum(X, 1) == d;
[sol, f, flag, out] = solve(p, 'Options', {QUIET}); slv = out.solver;
[xx, f2] = linprog(Cst(:), kron(ones(1, n), eye(m)), s, kron(eye(n), ones(1, m)), d(:), zeros(m*n, 1), [], {QUIET});
dx = max(abs(sol.X(:) - xx));""")
near('a transport problem: the objective linprog gives with the matrices written out', W['f'], W['f2'], 1e-9)
C('a transport problem: linprog chosen, exit flag 1', text(W['slv']) == 'linprog' and W['flag'] == 1, (W['slv'], W['flag']))
W, o = run("x = optimvar('x', 2, 'LowerBound', 0); y = optimvar('y', 'Type', 'integer', 'LowerBound', 0, 'UpperBound', 10);"
           "p = optimproblem('ObjectiveSense', 'maximize', 'Objective', x(1) + 2*x(2) + 3*y + 7);"
           "p.Constraints.c1 = x(1) + x(2) + y <= 4.5; p.Constraints.c2 = x(1) - x(2) >= -1;"
           "[sol, f, flag, out] = solve(p); slv = out.solver; xs = sol.x; ys = sol.y;")
C('a mixed-integer problem goes to intlinprog, and says so', text(W['slv']) == 'intlinprog' and 'Solving problem using intlinprog.' in o, (W['slv'], o[:80]))
near('a mixed-integer maximization: the answer and the objective with its constant', (W['ys'], W['xs'], W['f']), [4, 0, 0.5, 20], 1e-9)
# a knapsack against every choice
rs = np.random.default_rng(11)
wt, val = rs.integers(1, 20, 10).astype(float), rs.integers(1, 30, 10).astype(float)
cap = float(wt.sum() // 2)
best = max(val @ np.array(c) for c in itertools.product((0, 1), repeat=10) if wt @ np.array(c) <= cap)
W, _ = run(f"wt = {wt.tolist()}; val = {val.tolist()}; t = optimvar('t', 10, 'Type', 'integer', 'LowerBound', 0, 'UpperBound', 1);"
           f"p = optimproblem('ObjectiveSense', 'max', 'Objective', val*t); p.Constraints.w = wt*t <= {cap};"
           f"[sol, f] = solve(p, 'Options', optimoptions('intlinprog', 'Display', 'off'));")
near('a knapsack: the best of all 1024 choices', W['f'], best)

# ---- quadratic and nonlinear problems ---------------------------------------------------------------------------------------

W, o = run("""rng(5); k = 30; Q = randn(k); Q = Q'*Q/k + 0.01*eye(k); r = rand(k, 1)/10;
w = optimvar('w', k, 'LowerBound', 0, 'UpperBound', 0.2);
q = optimproblem('Objective', w'*Q*w - r'*w);
q.Constraints.budget = sum(w) == 1;
[sw, fq, fl, out] = solve(q, 'Options', optimoptions('quadprog', 'Display', 'off')); slv = out.solver;
[ww, fq2] = quadprog(2*Q, -r, [], [], ones(1, k), 1, zeros(k, 1), 0.2*ones(k, 1), [], optimoptions('quadprog', 'Display', 'off'));
dw = max(abs(ww - sw.w));""")
C('a portfolio goes to quadprog', text(W['slv']) == 'quadprog', W['slv'])
near('a portfolio: the answer quadprog gives with H and f written out', (W['fq'], W['dw']), (W['fq2'], 0.0), 1e-9)
W, o = run("z = optimvar('z', 2); p = optimproblem('Objective', 100*(z(2) - z(1)^2)^2 + (1 - z(1))^2);"
           "p.Constraints.disk = z(1)^2 + z(2)^2 <= 1; x0.z = [0; 0];"
           "[s, f, fl, out] = solve(p, x0, 'Options', optimoptions('fmincon', 'Display', 'off')); zs = s.z; slv = out.solver;"
           "u = optimproblem('Objective', 100*(z(2) - z(1)^2)^2 + (1 - z(1))^2); [su, fu, ~, ou] = solve(u, x0, 'Options', optimoptions('fminunc', 'Display', 'off')); slu = ou.solver; zu = su.z;")
from scipy.optimize import minimize  # noqa: E402
ref = minimize(lambda z: 100 * (z[1] - z[0] ** 2) ** 2 + (1 - z[0]) ** 2, [0, 0], method='SLSQP', tol=1e-12,
               constraints=[{'type': 'ineq', 'fun': lambda z: 1 - z[0] ** 2 - z[1] ** 2}])
C('Rosenbrock in the disk goes to fmincon', text(W['slv']) == 'fmincon', W['slv'])
near("Rosenbrock in the disk: SciPy's SLSQP answer", W['zs'], ref.x.reshape(2, 1), 1e-5)
C('with no constraints, fminunc', text(W['slu']) == 'fminunc', W['slu'])
near('Rosenbrock unconstrained: (1, 1)', W['zu'], [[1], [1]], 1e-4)
W, _ = run("k = optimvar('k', 2, 'Type', 'integer', 'LowerBound', -5, 'UpperBound', 5); rng(1);"
           "p = optimproblem('Objective', (k(1) - 1.4)^2 + (k(2) + 2.6)^2 + 0.1*sin(k(1)));"
           "[s, f, fl, out] = solve(p, 'Options', optimoptions('ga', 'Display', 'off')); ks = s.k; slv = out.solver;")
C('a nonlinear objective with integers goes to ga', text(W['slv']) == 'ga', W['slv'])
near('ga: the nearest integers', W['ks'], [[1], [-3]])

W, _ = run(f"x = optimvar('x', 2, 'LowerBound', 0); p = optimproblem('Objective', -x(1) - 2*x(2)); p.Constraints.c1 = x(1) + x(2) <= 4;"
           f"p.Constraints.c2 = [x(1) <= 3; x(2) - x(1) <= 1]; [s, f, fl, o, lam] = solve(p, 'Options', {QUIET}); l1 = lam.Constraints.c1; l2 = lam.Constraints.c2;"
           f"lo = lam.Variables.x.Lower; [~, ~, ~, ~, L2] = linprog([-1; -2], [1 1; 1 0; -1 1], [4; 3; 1], [], [], [0; 0], [], {QUIET}); li = L2.ineqlin;"
           "z = optimvar('z', 2); q = optimproblem('Objective', (z(1) - 2)^2 + (z(2) - 2)^2); q.Constraints = z(1)^2 + z(2)^2 <= 2;"
           "[~, ~, ~, ~, lz] = solve(q, struct('z', [0; 0]), 'Options', optimoptions('fmincon', 'Display', 'off')); lc = lz.Constraints;")
near("lambda by constraint name: linprog's multipliers in their places", (W['l1'], W['l2'], W['lo']), np.concatenate([a(W['li']).reshape(-1), [0, 0]]), 1e-9)
near('lambda of a nonlinear constraint (fmincon): 1, from the gradients at (1, 1)', W['lc'], 1.0, 1e-6)

# ---- equations -----------------------------------------------------------------------------------------------------------

W, o = run("u = optimvar('u', 2); eq = eqnproblem;"
           "eq.Equations.e1 = exp(-exp(-(u(1) + u(2)))) == u(2)*(1 + u(1)^2);"
           "eq.Equations.e2 = u(1)*cos(u(2)) + u(2)*sin(u(1)) == 0.5;"
           "[su, fu, flu, ou] = solve(eq, struct('u', [0; 0])); us = su.u; r1 = fu.e1; r2 = fu.e2; slv = ou.solver;")
C('nonlinear equations go to fsolve', text(W['slv']) == 'fsolve' and W['flu'] == 1, (W['slv'], W['flu']))
near('nonlinear equations: their residuals are near zero', (W['r1'], W['r2']), [0, 0], 1e-9)
us = a(W['us']).reshape(-1)
near('nonlinear equations: the answer satisfies them', [np.exp(-np.exp(-(us[0] + us[1]))) - us[1] * (1 + us[0] ** 2), us[0] * np.cos(us[1]) + us[1] * np.sin(us[0]) - 0.5], [0, 0], 1e-9)
W, _ = run("v = optimvar('v', 3); le = eqnproblem('Equations', [1 2 3; 4 5 6; 7 8 10]*v == [1; 2; 3]); [sv, fv, fl] = solve(le); vs = sv.v;"
           "b = optimvar('b', 'LowerBound', 0); be = eqnproblem('Equations', b^2 == 4); [sb, ~, ~, ob] = solve(be, struct('b', 1)); bs = sb.b; slb = ob.solver;")
near('linear equations solved exactly', W['vs'], np.linalg.solve([[1, 2, 3], [4, 5, 6], [7, 8, 10]], [[1], [2], [3]]), 1e-12)
C('a bounded equation goes to lsqnonlin', text(W['slb']) == 'lsqnonlin', W['slb'])
near('a bounded equation: the root within the bounds', W['bs'], 2.0, 1e-7)

# ---- fcn2optimexpr, prob2struct, varindex, show ---------------------------------------------------------------------------------

_, o = run("r = optimvar('r', 2); e = fcn2optimexpr(@(v) v.^2 + 1, r)")
C('fcn2optimexpr: a function expressions can follow stays quadratic', 'Quadratic' in o and 'r(1)^2 + 1' in o, o)
W, o = run("r = optimvar('r', 2); fe = fcn2optimexpr(@(v) besselj(0, v(1)) + v(2)^2, r)\n"
           "pp = optimproblem('Objective', fe); pp.Constraints.b = r(1) >= 1;"
           "[sr, fr] = solve(pp, struct('r', [2; 1]), 'Options', optimoptions('fmincon', 'Display', 'off')); rs = sr.r;")
C('fcn2optimexpr: another function is called at each point, named in the text', 'anonymousFunction1(r)' in o and 'where:' in o, o)
from scipy.special import j0  # noqa: E402
from scipy.optimize import minimize_scalar  # noqa: E402
jr = minimize_scalar(j0, bounds=(2, 5), method='bounded', options={'xatol': 1e-12})
near("fcn2optimexpr: the minimum of besselj(0, r) + r^2: SciPy's", (W['rs'], W['fr']), (jr.x, 0.0, jr.fun), 1e-5)
W, _ = run("y = optimvar('y'); fo = fcn2optimexpr(@(t) [sin(t); cos(t)], y, 'OutputSize', [2 1], 'Analysis', 'off'); v = evaluate(fo, struct('y', pi/2)); sz = size(fo);")
near("fcn2optimexpr with OutputSize and 'Analysis' 'off'", (W['v'], W['sz']), [1, 0, 2, 1], 1e-12)
W, _ = run("x = optimvar('x', 2, 'LowerBound', 0); y = optimvar('y', 'Type', 'integer', 'LowerBound', 0, 'UpperBound', 10);"
           "p = optimproblem('ObjectiveSense', 'maximize', 'Objective', x(1) + 2*x(2) + 3*y + 7); p.Constraints.c1 = x(1) + x(2) + y <= 4.5;"
           "ps = prob2struct(p); ps.options = optimoptions('intlinprog', 'Display', 'off'); [xx, fv] = intlinprog(ps); f0 = ps.f0; slv = ps.solver;"
           "idx = varindex(p); ix = idx.x; iy = varindex(p, 'y');")
near('prob2struct: intlinprog of it gives the same answer (negated, with f0)', (W['xx'], -(W['fv'] + W['f0'])), [0, 0.5, 4, 20], 1e-9)
C('prob2struct: the solver solve would use', text(W['slv']) == 'intlinprog', W['slv'])
near('varindex: alphabetical order of names', (W['ix'], W['iy']), [1, 2, 3])
W, _ = run("z = optimvar('z', 2); p = optimproblem('Objective', (z(1) - 1)^2 + exp(z(2))); p.Constraints.c = z(1)^2 + z(2)^2 <= 1;"
           "s = prob2struct(p, struct('z', [0; 0])); v = s.objective([1; 0]); [c, ceq] = s.nonlcon([1; 1]); slv = s.solver;")
near('prob2struct: objective and nonlcon as functions of the vector', (W['v'], W['c']), [1, 1])
C('prob2struct: fmincon for a nonlinear problem', text(W['slv']) == 'fmincon', W['slv'])
_, o = run("x = optimvar('x', 2, 'LowerBound', 0); y = optimvar('y', 'Type', 'integer', 'UpperBound', 10);"
           "p = optimproblem('ObjectiveSense', 'maximize', 'Objective', x(1) + 2*x(2) + 3*y); p.Constraints.c1 = x(1) + x(2) + y <= 4; show(p)\n showbounds(y)")
C('show: variables, integers, objective, constraints, bounds',
  all(t in o for t in ('Solve for:', 'x, y', 'where: y integer', 'maximize :', 'x(1) + 2*x(2) + 3*y', 'subject to c1:', 'x(1) + x(2) + y <= 4', '0 <= x(1)', 'y <= 10')), o)

# ---- problems are values ------------------------------------------------------------------------------------------------------

W, _ = run("x = optimvar('x'); p = optimproblem('Objective', x); p.Constraints.a = x >= 1; q = p; q.Constraints.b = x <= 3; q.Description = 'q';"
           "np = numel(fieldnames(p.Constraints)); nq = numel(fieldnames(q.Constraints)); dp = p.Description;")
C('a problem is a value: a copy changes alone', W['np'] == 1 and W['nq'] == 2 and text(W['dp']) == '', (W['np'], W['nq'], W['dp']))

# ---- solve's other meanings are kept -------------------------------------------------------------------------------------------

W, _ = run("syms t; r = double(solve(t^2 - 4 == 0, t)); F = ode(ODEFcn=@(t, y) -y, InitialValue=1); S = solve(F, 0, 1); y1 = S.Solution(end);")
near('solve of symbolic equations still solves them', np.sort(a(W['r']).reshape(-1)), [-2, 2])
near('solve of an ode object still solves it', W['y1'], np.exp(-1), 1e-4)

# ---- refusals ------------------------------------------------------------------------------------------------------------------

raises("x = optimvar('x', 2); solve(optimproblem('Objective', x(1)^2 + exp(x(2))))", 'needs an initial point')
raises("x = optimvar('x', 2); solve(optimproblem('Objective', sum(x) + sum(optimvar('x', 2))))", "Two different variables are named 'x'")
raises("optimvar('1x')", 'valid variable name')
raises("y = optimvar('y', {'a', 'b'}); y('c')", "'c' is not an index name of y")
raises("x = optimvar('x', 2); solve(optimproblem('Objective', x(1)^2 + x(2)^2), 'Solver', 'linprog')", 'linprog solves linear problems')
raises("x = optimvar('x', 2); solve(optimproblem('Objective', exp(x(1))), struct('z', 1))", 'no value for x')
raises("x = optimvar('x', 2); solve(optimproblem('Objective', x), struct('x', [1; 1]))", 'scalar')
raises("x = optimvar('x', 2); eqnproblem('Equations', x(1) <= 1)", 'Equations are equalities')
raises("x = optimvar('x', 2); p = optimproblem; p.Constraints = 5", 'constraint array or a struct')
raises("x = optimvar('x', 2); evaluate(sum(x), struct('x', [1 2 3]))", 'has 2 elements')
raises("optimvar('z', 2, 'Type', 'binary')", "'continuous' or 'integer'")
raises("x = optimvar('x', 2); solve(optimproblem('Objective', exp(x(1))), struct('x', [1; 1]), 'Solver', 'fminbnd')", "'fminbnd' is not a solver")
_, o = run("x = optimvar('x', 2); try, solve(optimproblem('Objective', exp(x(1))), 'Solver', 'fmincon'); catch, end")
C('a refused request writes no "Solving problem using"', 'Solving problem' not in o, o)

# ---- paretosearch ---------------------------------------------------------------------------------------------------------------

W, o = run("fun = @(x) [x(1)^2 + x(2)^2, (x(1) - 2)^2 + x(2)^2]; [X, F, fl, out] = paretosearch(fun, 2, [], [], [], [], [-5 -5], [5 5]); n = size(X, 1); msg = out.message;")
F = a(W['F'])
C('paretosearch: ParetoSetSize (60) points', W['n'] == 60, W['n'])
near('paretosearch: on the front (sqrt(f1) + sqrt(f2) = 2, x2 = 0)', (np.sqrt(F[:, 0]) + np.sqrt(F[:, 1]), a(W['X'])[:, 1]), np.concatenate([np.full(60, 2.0), np.zeros(60)]), 1e-4)
C('paretosearch: no point dominates another', not any(np.all(F[j] <= F[i]) and np.any(F[j] < F[i]) for i in range(len(F)) for j in range(len(F))))
C('paretosearch: sorted by the first objective, both ends reached', np.all(np.diff(F[:, 0]) >= 0) and F[0, 0] < 1e-8 and F[-1, 1] < 1e-8, F[[0, -1]])
W, _ = run("f3 = @(x) [x(1)^2 + x(2)^2 + x(3)^2, (x(1)-1)^2 + x(2)^2 + x(3)^2, x(1)^2 + (x(2)-1)^2 + x(3)^2];"
           "op = optimoptions('paretosearch', 'Display', 'off', 'ParetoSetSize', 20); [X3, F3] = paretosearch(f3, 3, [], [], [], [], -2*ones(1, 3), 2*ones(1, 3), [], op);")
X3 = a(W['X3'])
C('paretosearch: three objectives, ParetoSetSize points, all in the triangle of the three minima (the front)',
  len(X3) == 20 and np.all(np.abs(X3[:, 2]) < 1e-5) and np.all(X3[:, :2] >= -1e-5) and np.all(X3[:, 0] + X3[:, 1] <= 1 + 1e-5), X3)
W, _ = run("g = @(x) [x(1), (1 + x(2))*(1 - (x(1)/(1 + x(2)))^2)]; op = optimoptions('paretosearch', 'Display', 'off', 'ParetoSetSize', 15);"
           "[X, F] = paretosearch(g, 2, [], [], [], [], [0 0], [1 1], [], op);")
F = a(W['F'])
near('paretosearch: a concave front (f2 = 1 - f1^2), reached all along', (F[:, 1] - (1 - F[:, 0] ** 2), a(W['X'])[:, 1]), np.zeros(2 * len(F)), 1e-6)
C('paretosearch: the concave front covered from end to end, evenly', 13 <= len(F) <= 15 and F[0, 0] < 1e-8 and F[-1, 1] < 1e-8 and np.max(np.diff(F[:, 0])) < 0.15, F[:, 0])
W, _ = run("fun = @(x) [x(1), 1 - x(1) + x(2)^2]; nl = @(x) deal(0.3 - x(1), []); op = optimoptions('paretosearch', 'Display', 'off', 'ParetoSetSize', 10);"
           "X = paretosearch(fun, 2, [], [], [], [], [0 -1], [1 1], nl, op);")
X = a(W['X'])
C('paretosearch: a nonlinear constraint holds on every point', np.all(X[:, 0] >= 0.3 - 1e-6) and len(X) == 10, X)

sys.exit(C.done())
