"""How PyLAB computes each function: the "How it works" that help NAME
prints after the call forms and the Help panel sets out as paragraphs.

The texts are written below: a line `name:` starts an entry (several names
`a, b, c:` share one), lines indented by four spaces are prose (a blank line
ends a paragraph), and lines indented by eight are formulas, kept as
written. Each entry says where in the engine the function is (its Python
file) and what computes it, with the NumPy and SciPy names it calls; a test
checks that every function has an entry and that each NumPy or SciPy name
quoted exists. The functions of each distribution family (normpdf,
normcdf, norminv, normrnd, normstat, and the fits and likelihoods) are
made from a table of the families' scipy.stats distributions, at the end.
"""

_TEXT = r"""
odeset:
    Python: funfun.py and odesolvers.py. The solvers are Python classes that SciPy's solve_ivp drives one step at a time (each is a scipy.integrate.OdeSolver): ode45 and ode23 are SciPy's own RK45 and RK23, the others are PyLAB's, in the engine's file odesolvers.py. solve_ivp asks the class for a step, keeps it, evaluates the class's interpolant where a value between steps is wanted, and watches the event functions. What follows is what the solvers share; each solver's help describes its method.

    The one-step solvers (ode45, ode23, ode78, ode89, ode23s, ode23t, ode23tb) accept a step when the root mean square of its estimated local error e, each component measured against its own tolerance, is at most 1:
        err = sqrt(mean((e ./ (AbsTol + RelTol*max(|y_old|, |y_new|))).^2))
    The next step, or the retry of a rejected one, is
        after an accepted step:   h_next  = h * min(10, 0.9 * err^(-1/(q+1)))
        after a rejected step:    h_retry = h * max(0.2, 0.9 * err^(-1/(q+1)))
    where q is the order of the error estimate; once a step has been rejected, the step accepted after it does not grow. ode113 and ode15s choose their order as well as their step, by rules described in their help.

    RelTol defaults to 1e-3 (and is at least 100*eps), AbsTol to 1e-6, as one value or one for each component. The first step is InitialStep, or comes from the sizes of y0 and f(t0, y0) and the change of f over a trial step (the rule in Hairer, Norsett and Wanner, Solving ODEs I, II.4). No step is longer than MaxStep, by default a tenth of the time span, and the last one ends exactly at tf.

    With tspan = [t0 tf] the result holds the solver's own steps, and Refine (4 for ode45 and ode89, 8 for ode78, 1 for the others) adds Refine - 1 points inside each step, from the interpolant. With more values in tspan the result holds exactly those, all from the interpolant. sol = ode45(...) keeps the steps and the interpolants for deval and odextend.

    Events: after each step every event function is evaluated at its end. A change of sign in the direction asked for is located on the step's interpolant by Brent's method, and a terminal one ends the solution there.

    OutputFcn: the solution is computed first; the output function is then called with 'init', with each step's times and states, and with 'done', as it would be during the solution, and an answer of true cuts the result at that step.

    NonNegative: the components it names are passed to odefun as max(y, 0), and a derivative that would take one of them further below zero is set to zero.

    Mass: the nonstiff solvers solve M y' = f for y' at each evaluation of odefun (a constant M is factorised once); the stiff ones put M into their Newton matrix. M(t) is called with t alone when MStateDependence is 'none' or the function takes one input, else as M(t, y). Jacobian: the stiff solvers take df/dy from this option (a matrix, or a function of t and y) or by forward differences (SciPy's num_jac, which adapts each column's increment from one call to the next).
ode45:
    Python: SciPy's scipy.integrate.RK45, driven by solve_ivp.

    An explicit Runge-Kutta pair with Dormand and Prince's coefficients. A step evaluates odefun six times: five times at points reached from the slopes found so far, and once at the step's result, which serves as the first slope of the next step. The seven slopes are combined in two ways: a result of order 5, which is kept, and one of order 4. Their difference is the error estimate, of order q = 4: the exponent in odeset's step rule is -1/5.

    Values between steps come from a quartic polynomial in the fraction of the step, built from the same slopes: Refine's points cost no evaluations of odefun.
ode23:
    Python: SciPy's scipy.integrate.RK23, driven by solve_ivp.

    An explicit Runge-Kutta pair with Bogacki and Shampine's coefficients: three new slopes a step (the slope at its end is reused as the first of the next), a result of order 3 that is kept and one of order 2 for the error (q = 2, so the exponent in odeset's step rule is -1/3). Values between steps come from the cubic through y and f at the two ends of the step.
ode113:
    Python: class Adams in odesolvers.py, a translation of Shampine and Gordon's STEP and INTRP (the routines DSTEPS and DINTP of SLATEC's DDEABM, which are in the public domain), with its arrays numbered from 1 as in the Fortran so that each line can be checked against it.

    An Adams method represents the derivative of the solution by the polynomial through its last k values, k (the order) from 1 to 12. The values are kept as modified divided differences phi, which let the step size vary. A step from t to t + h is a PECE cycle:
        predict:   p = y + h * sum(g(i) * phi(i), i = 1..k)        (Adams-Bashforth, order k)
        evaluate:  f(t + h, p)
        correct:   y_new = p + h * g(k+1) * (f(t + h, p) - its predicted value)   (Adams-Moulton, order k + 1)
        evaluate:  f(t + h, y_new), and the differences are updated
    so odefun is evaluated twice a step whatever the order. The coefficients g depend on the last k step sizes and are recomputed only when the step changes.

    The local error is estimated from the size of the correction, against RelTol*|y| + AbsTol (root mean square), and the step fails when the estimate exceeds 1. From the same differences the code estimates the error the step would have had at orders k - 2, k - 1 and k + 1, and lowers or raises the order when that promises a smaller error. At the start the order rises by one and the step doubles at every step until an estimate says to stop. Then the step doubles when the error estimate is below 2^-(k+2), stays when it is below 1/2, and otherwise shrinks by (0.5/err)^(1/(k+1)), kept between 0.5 and 0.9. A failed step is retried with half the step (from the fourth failure in a row, with the shorter step the error estimate asks for, if it asks for one), and from the third failure in a row at order 1.

    Values between steps (Refine, tspan, events, deval) come from the same Adams polynomial the step was taken with (INTRP), so they cost no evaluations of odefun. Near the limits of double precision the sums are compensated, and tolerances below what the arithmetic can give are raised.
ode78:
    Python: class Verner78 in odesolvers.py; the coefficients are in vernertab.py.

    Verner's "most efficient" Runge-Kutta pair of orders 8 and 7: thirteen stages, that is twelve evaluations of odefun inside the step and one at its end, which is the first slope of the next step. The result of order 8 is kept, and its difference from the one of order 7 is the error estimate (q = 7, so the exponent in odeset's step rule is -1/8).

    Values between steps come from Verner's interpolant of order 7, with polynomials b_i of degree 8 in the fraction s of the step:
        y(t + s*h) = y + h * sum(b_i(s) * k_i)
    It needs eight more stages, the first of them the slope at the step's end; they are evaluated only for steps in which a value is asked (Refine, tspan, events, deval).

    The coefficients were generated from the exact values (rationals and 40-digit decimals) of the Julia package OrdinaryDiffEq.jl (MIT license), each rounded once to the nearest double, after checking that the weights sum to 1, every node is its row's sum, the quadrature conditions hold to order 8 and the interpolant gives the step's own result at its end.
ode89:
    Python: class Verner89 in odesolvers.py; the coefficients are in vernertab.py.

    Verner's "most efficient" Runge-Kutta pair of orders 9 and 8: sixteen stages, fifteen evaluations of odefun inside the step and one at its end, which is the first slope of the next step. The result of order 9 is kept, and its difference from the one of order 8 is the error estimate (q = 8, so the exponent in odeset's step rule is -1/9).

    Values between steps come from Verner's interpolant of order 8 (polynomials of degree 9 in the fraction of the step), which needs ten more stages, the first of them the slope at the step's end; they are evaluated only for steps in which a value is asked.

    The coefficients were generated from the exact values (rationals, 40-digit decimals and sums with sqrt(6)) of the Julia package OrdinaryDiffEq.jl (MIT license), each rounded once to the nearest double, after the same checks as ode78's, to order 9.
ode15s:
    Python: class NDF in odesolvers.py: SciPy's scipy.integrate.BDF, written also for M(t, y) y' = f(t, y). Without a mass matrix it takes exactly the steps SciPy's BDF takes.

    A multistep method of order k from 1 to 5. The solution is represented by the polynomial through its last k + 1 values, kept as backward differences at equal spacing; when the step size changes they are interpolated to the new spacing. A step predicts y from that polynomial, then solves for the correction d with
        y' = (psi + d)/c,   c = h/alpha_k
    where psi comes from the differences, and y' = f(t, y) (or M y' = f). The equation is solved by simplified Newton (at most four iterations) with the matrix I - c*J (M - c*J), factorised by LU and kept while the step size stays. J is kept from step to step and evaluated again at the predicted point only when Newton fails; if Newton fails with a fresh J, the step is halved.

    The NDFs differ from the backward differentiation formulas by Klopfenstein and Shampine's terms kappa (-0.1850, -1/9, -0.0823, -0.0415 for orders 1 to 4), which make them a little more accurate for the same stability; BDF 'on' sets kappa to 0.

    The error is estimated from the correction itself: d times a constant that depends on the order. A step whose error exceeds 1 (root mean square, against AbsTol + RelTol*|y|) is retried shorter, by 0.9*err^(-1/(k+1)) but not below 0.2. After k + 1 steps of one size, the errors at orders k - 1 and k + 1 are estimated from the differences, and the order allowing the longest next step is taken (MaxOrder caps it), the step growing at most tenfold. Values between steps come from the same polynomial.

    A singular mass matrix (an index-1 DAE): before the first step, the algebraic part of y0 (the directions M does not see) is moved by Newton's method until the algebraic equations hold, and y'0 is the least-norm solution of M y'0 = f. The same steps then solve M y' = f, the rows of M that are zero becoming equations for the algebraic variables.
ode23s:
    Python: class Rosenbrock23 in odesolvers.py: the modified Rosenbrock pair of order 2(3) of Shampine and Reichelt, "The MATLAB ODE Suite", SIAM J. Sci. Comput. 18 (1997).

    A linearly implicit one-step method: no Newton iteration, but at every step a new Jacobian J (unless the Jacobian option gives a constant matrix), the time derivative f_t by a one-sided difference, and one LU of W = M - h*d*J with d = 1/(2 + sqrt(2)). A step:
        k1 = W \ (f(t, y) + h*d*f_t)
        f1 = f(t + h/2, y + h/2*k1)
        k2 = W \ (f1 - M*k1) + k1
        y_new = y + h*k2                                     (order 2)
        k3 = W \ (f(t+h, y_new) - (6+sqrt(2))*(M*k2 - f1) - 2*(M*k1 - f(t, y)) + h*d*f_t)
        e = h/6 * (k1 - 2*k2 + k3)                           (the error, q = 2)
    The exponent in odeset's step rule is -1/3. Values between steps come from the free interpolant
        y(t + s*h) = y + h * (s*(1-s)*k1 + s*(s-2d)*k2) / (1-2d)
    The mass matrix, if any, must be constant.
ode23t:
    Python: class Trapezoid in odesolvers.py.

    The trapezoidal rule, written for a mass matrix:
        M (y_new - y - h/2*y') = h/2 * f(t + h, y_new)
    where y' is the derivative at the step's start (M y' = f). It is solved by simplified Newton with W = M - h/2*J, factorised by LU; J is kept from step to step and evaluated again only when Newton fails (then the step is halved if it still fails). Newton starts from the straight line through the last two solution values.

    The rule is A-stable but does not damp: a component far stiffer than the step keeps its error, alternating in sign, instead of losing it. So the local error, h^3*y'''/12, is estimated with y''' from the third divided difference of the last four solution values: a ringing component then counts at its own size, not multiplied by its stiffness. For the first two steps, before there are four values, the derivative at the middle of the step is compared with the mean of the end ones and the difference passed through W. The exponent in odeset's step rule is -1/3.

    Values between steps come from the quadratic through the previous solution value and the two ends of the step (for the first step, through the start's value and slope and the end).

    A singular mass matrix (an index-1 DAE): the algebraic part of y0 is first made consistent, as for ode15s. The algebraic equations then hold exactly at the end of each step, and the error is measured in the differential directions only.
ode23tb:
    Python: class TRBDF2 in odesolvers.py: TR-BDF2 as Hosea and Shampine, Appl. Numer. Math. 20 (1996), implement it.

    Two implicit stages that share one Newton matrix. With gamma = 2-sqrt(2) and d = gamma/2:
        trapezoidal stage to t + gamma*h:   M (y_g - y - d*h*y') = d*h * f(t + gamma*h, y_g)
        BDF2 stage to t + h:   M (y_new - (y_g - (1-gamma)^2*y)/(gamma*(2-gamma))) = d*h * f(t + h, y_new)
    For this gamma both stages have the matrix W = M - d*h*J, factorised once for each step size. Each stage is solved by simplified Newton (J is kept from step to step and evaluated again only when Newton fails), the first starting from y + gamma*h*y' and the second from the line through y and y_g.

    The BDF2 stage damps what the trapezoidal stage leaves in a very stiff component (the pair is L-stable). The error is Hosea and Shampine's estimate from the three slopes, passed through W so that stiff components do not inflate it:
        e = W \ (h * M * (-0.1381*y'(t) + 0.3333*y'(t + gamma*h) - 0.1953*y'(t + h)))
    (with M y' = f; q = 2, so the exponent in odeset's step rule is -1/3). Values between steps come from the quadratic through y, y_g and y_new. The mass matrix may vary with t and y but must be nonsingular.
ode15i:
    Python: class NDF in odesolvers.py, as for ode15s, in its form for F(t, y, y') = 0 and with the plain backward differentiation formulas (kappa 0).

    The steps are those of ode15s, but the equation solved at each step is F(t, y, (psi + d)/c) = 0, by simplified Newton with the matrix c*dF/dy + dF/dy'. The two derivatives come from the Jacobian option (a cell {dFdy, dFdyp}, or a function returning both) or by forward differences of F in y and in y'. As dF/dy' may be singular, a DAE of index 1 is solved like an implicit ODE.

    The start must satisfy F(t0, y0, yp0) = 0. When dF/dy' is nonsingular (an implicit ODE), Newton's method corrects yp0 to fit y0, with a warning if the change exceeds the tolerances. Otherwise the least-squares correction of y0 and yp0 is computed, and if it exceeds the tolerances the start is refused: decic finds values that fit. The first step is 1% of |y0|/|yp0| in the error norm (or InitialStep), and MaxOrder caps the order.
decic:
    Python: funfun.py. Gauss-Newton on F(t0, y, yp) = 0. Each iteration evaluates F and its derivatives in y and yp (from the Jacobian option or by forward differences) and takes the least-squares step of least norm in the components that are free, numpy.linalg.lstsq; the held ones do not move. It stops when the step is below 1e-13 of the values, or after 100 iterations. resnrm is the 2-norm of F at the result.
deval:
    Python: funfun.py. sol keeps the interpolant of each step (SciPy's OdeSolution over the solver's dense outputs, the same polynomials the solver's own help describes), and deval evaluates the one whose step holds each time. The interpolants were built during the solution, so deval evaluates odefun no more. The solutions of bvp4c, bvp5c, dde23 and ddesd: their own interpolants (odemore.py), and their derivatives.
odextend:
    Python: funfun.py. The solver that made sol runs again from its last point (or the y0 given) to the new end, with sol's options unless others are given, and its steps and interpolants are joined to sol's.
# ---- elfun.py: element-wise mathematics -------------------------------------------------------
sqrt:
    Python: elfun.py. numpy.sqrt element by element, or math.sqrt for a scalar double. When a real argument has a negative element, the whole array is taken as complex and numpy.sqrt gives the complex roots, so sqrt(-4) is 0 + 2i. Char and logical count as double, single stays single, and integers are refused.
exp:
    Python: elfun.py. numpy.exp element by element, or math.exp for a scalar double (Inf above 709). Single stays single; integers are refused. Of -tau*s: control.py, a delay.
expm1:
    Python: elfun.py. numpy.expm1, which computes exp(x) - 1 without the cancellation near x = 0 (math.expm1 for a scalar double).
log, log10:
    Python: elfun.py. numpy.log and numpy.log10 element by element (math.log and math.log10 for a scalar double). When a real argument has a negative element the whole array is taken as complex, which gives log(-x) + pi*1i (pi/log(10) for log10); log(0) is -Inf. With a test case first: unittests.py, the message written when the run reports at that level.
log1p:
    Python: elfun.py. numpy.log1p, which computes log(1 + x) without the rounding of 1 + x near 0. Below -1 the array is taken as complex and log(1 + z) is computed.
log2:
    Python: elfun.py. numpy.log2 (complex when an element is negative). With two outputs, numpy.frexp splits x into a mantissa f in [0.5, 1) and a whole exponent e with x = f*2^e, for the real part of a complex x.
realsqrt:
    Python: elfun.py. numpy.sqrt with no switch to complex numbers: a negative element gives NaN.
reallog:
    Python: elfun.py. numpy.log, after an error if any element is negative.
realpow:
    Python: elfun.py. The power operator .^ of the language (the same code as x.^y), then an error if the result is complex.
pow2:
    Python: elfun.py. 2.^x by NumPy's power. pow2(f, e) is f.*2.^e, by numpy.ldexp (an exact change of the exponent) when every e is a whole number and f is real; single stays single.
nextpow2:
    Python: elfun.py. numpy.frexp of abs(x) gives x = f*2^e with f in [0.5, 1); the result is e, or e - 1 when f is exactly 0.5 (x is a power of two), 0 for 0, Inf for Inf and NaN for NaN. For integers, the bit length of abs(x) - 1, exact for 64-bit values. The class is kept.
nthroot:
    Python: elfun.py. sign(x).*abs(x).^(1./n) by NumPy, then one Newton step r - (r^n - x)/(n*r^(n-1)), which makes an exact root such as nthroot(27, 3) come out exactly. Complex inputs, and a negative x with an n that is not an odd integer, are refused.
hypot:
    Python: elfun.py. numpy.hypot of the absolute values: sqrt(a.^2 + b.^2) without overflow or underflow in the squares.
sin, cos, tan, sinh, cosh, tanh, atan, asinh:
    Python: elfun.py. The NumPy function of the same meaning (numpy.sin, numpy.cos, numpy.tan, numpy.sinh, numpy.cosh, numpy.tanh, numpy.arctan, numpy.arcsinh) element by element, real or complex; a scalar double goes through Python's math module instead (sin, cos, tan, tanh, atan, asinh). Char and logical count as double, single stays single, and integers are refused.
sec, csc, cot, sech, csch, coth:
    Python: elfun.py. The reciprocal of the NumPy function: 1./numpy.cos(x), 1./numpy.sin(x), 1./numpy.tan(x), 1./numpy.cosh(x), 1./numpy.sinh(x), 1./numpy.tanh(x).
asin, acos, acosh, atanh:
    Python: elfun.py. numpy.arcsin, numpy.arccos, numpy.arccosh and numpy.arctanh. When a real argument has an element outside the real domain (abs(x) > 1 for asin, acos and atanh, x < 1 for acosh), the whole array is taken as complex and the complex function value is returned.
asec, acsc, acot, asech, acsch, acoth:
    Python: elfun.py. Through the reciprocal: numpy.arccos(1./x), numpy.arcsin(1./x), numpy.arctan(1./x), numpy.arccosh(1./x), numpy.arcsinh(1./x), numpy.arctanh(1./x), complex where the real function is undefined (as for asin and acos).
sind, cosd, tand, secd, cscd, cotd:
    Python: elfun.py. sind and cosd take abs(x) mod 360 as a quarter turn and the rest in [-45, 45] degrees, so that numpy.sin and numpy.cos only see small angles, exact at multiples of 90; sind is odd and cosd even. For complex x, sin(a + ib) = sin(a) cosh(b) + i cos(a) sinh(b) (and so for cos) with the exact real parts. tand is 0, +-Inf and +-1 at multiples of 180, odd multiples of 90 and of 45; secd, cscd and cotd are the reciprocals.
asind, acosd, atand, asecd, acscd, acotd:
    Python: elfun.py. numpy.rad2deg of the inverse function in radians (numpy.arcsin(x), numpy.arccos(x), numpy.arctan(x), and of 1./x for asecd, acscd and acotd), complex outside the real domain.
sinpi, cospi:
    Python: elfun.py. sin(pi*mod(x, 2)) and cos(pi*mod(x, 2)) by NumPy, set exactly to 0 at whole x (sinpi) and at x + 1/2 (cospi), where pi*x is not exact.
deg2rad, rad2deg:
    Python: elfun.py. x*(pi/180) and x*(180/pi).
atan2:
    Python: elfun.py. numpy.arctan2(y, x) element by element (math.atan2 for two scalars), with implicit expansion; complex inputs are refused.
atan2d:
    Python: elfun.py. numpy.rad2deg(numpy.arctan2(y, x)).
floor, ceil, fix:
    Python: elfun.py. numpy.floor, numpy.ceil and numpy.trunc. Integer arrays are returned as they are; logical and char give double; for a complex array the real and imaginary parts are rounded separately; single stays single.
round:
    Python: elfun.py. Halves go away from zero: numpy.trunc(x), plus sign(x) where the fraction is at least 0.5 (NumPy's own rounding takes halves to the even number, so it is not used). round(x, n) scales by 10^n, rounds and scales back (n < 0 divides by 10^-n first), and round(x, n, 'significant') takes n digits from the leading one, found with numpy.log10. Integer arrays are returned as they are.
mod, rem:
    Python: elfun.py. With q = x./y, n is the whole number nearest q when q is within one rounding of it, else floor(q) for mod and fix(q) for rem; the result is x - n.*y. mod then gives it the sign of y. Special values: mod(x, 0) is x and rem(x, 0) NaN; with y infinite, rem gives x and mod gives x or y by their signs; an infinite x gives NaN. For integer classes the values are rounded, computed in doubles and returned in the class.
idivide:
    Python: elfun.py. a./b in doubles, rounded by fix (the default), floor, ceil or round, and returned in the integer class (saturating at its limits).
bitand, bitor, bitxor:
    Python: elfun.py. numpy.bitwise_and, numpy.bitwise_or and numpy.bitwise_xor on the integer class of the inputs. Doubles are taken as whole numbers of an assumed type, uint64 unless one is named, and the result is double; a double that is not a whole number in that type's range is refused.
bitget, bitset:
    Python: elfun.py. The bits of the unsigned integer type of the same width (a negative value's two's complement): bitget is (u >> (b - 1)) & 1 and bitset sets or clears the bit with a mask, by NumPy's shift and bitwise operators.
bitshift:
    Python: elfun.py. On the bits of the integer type: a left shift moves the pattern up and drops what passes the top; a right shift moves it down, a signed value filling with its sign bit (rounding toward -Inf). Shifts of the type's width or more give 0 (or -1 for a negative value shifted right). The older third input n keeps only the lowest n bits of the result.
bitcmp:
    Python: elfun.py. numpy.invert: every bit of the integer type flipped. The older form bitcmp(a, n) flips only the lowest n bits, with an exclusive or.
sign:
    Python: elfun.py. numpy.sign; for complex values z./abs(z), and 0 at 0. Integers keep their class; char and logical give double.
abs:
    Python: elfun.py. numpy.abs. Integers are taken through doubles and back to their class, so abs(int8(-128)) saturates to 127; char and logical give double; single stays single.
real, imag, conj:
    Python: elfun.py. The real and imaginary parts of a complex array (numpy's .real and .imag) and numpy.conj, the class kept; imag of a real array is zeros, and char gives double.
angle:
    Python: elfun.py. numpy.angle: the phase atan2(imag(z), real(z)) in radians.
complex:
    Python: elfun.py. A complex double array (NumPy complex128) with its real and imaginary parts set directly: a + b*1i would make an infinite b into NaN + Inf i. The result stays complex even where b is 0, unlike a + 0i; single parts give a single result.
isnan, isinf, isfinite:
    Python: elfun.py. numpy.isnan, numpy.isinf and numpy.isfinite for double and single values; integers, char and logical are never NaN or Inf. isnan of a string array is true for its missing strings; cells and structs are refused.
ismissing:
    Python: elfun.py and missingdata.py. The standard missing value of each kind: NaN for numbers, a missing string in a string array, a space in char, and an empty char vector in a cell of text; NaT (NaN seconds), a duration of NaN, a calendarDuration with a NaN part, a category code of 0. A table's variables are read in turn and put side by side, a variable of a kind with no missing value counting none.
cplxpair:
    Python: elfun.py. Along the first dimension that is not 1 (or the one given): values whose imaginary part is within tol (100*eps unless given) times max(abs(z), 1) count as real. The others are sorted by real part, each matched with its conjugate (within twice tol) and the pair given as the conjugate of their mean and the mean; the real ones come last, sorted. One left without a partner is an error.
unwrap:
    Python: elfun.py. numpy.unwrap along the dimension (the first that is not 1 unless given): a jump larger than the tolerance (pi unless given, and never less than pi) is taken back by a multiple of 2*pi.
gcd:
    Python: elfun.py. numpy.gcd on 64-bit integers (non-integers are refused). With three outputs, the Bezout coefficients u and v (g = u*a + v*b) come from the extended Euclidean algorithm, run for each element in Python's integers.
lcm:
    Python: elfun.py. numpy.lcm of the absolute values, on 64-bit integers.
factorial:
    Python: elfun.py. scipy.special.gamma(n + 1), rounded to a whole number, and Inf above 170, where it overflows; integer inputs keep their class.
nchoosek:
    Python: elfun.py. For a number n, math.comb (exact, in Python's integers), with a warning above 2^53 where a double cannot hold it exactly. For a vector, every combination of k of its elements by itertools.combinations, in the order of their positions.
primes:
    Python: elfun.py. The sieve of Eratosthenes on a NumPy array of flags: the multiples of each prime up to sqrt(n) are struck out.
isprime:
    Python: elfun.py. A sieve of Eratosthenes up to the largest element when it is at most 10^7; otherwise each element in Python's integers, trial division by the primes to 37 and then Miller-Rabin with the bases 2 to 37, which decide every number below 2^64, so 64-bit integers are tested exactly.
factor:
    Python: elfun.py. Trial division by 2 and then the odd numbers, in Python's integers; what is left above 1 is the last prime factor.
perms:
    Python: elfun.py. itertools.permutations of the vector taken from its end, so the rows come in reverse lexicographic order of positions.
rats:
    Python: elfun.py. Each value as text in the rational display format (the one format rat uses), padded to 13 characters.
rat:
    Python: elfun.py. A continued fraction: the whole part k (rounded half away from zero) is taken off and the rest inverted, the convergents n/d built up, until abs(x - n/d) is below the tolerance (1e-6*norm of the finite elements, 1-norm, unless given), at most 64 terms; Inf gives 1/0 and NaN 0/0. With one output, the continued fraction as text, '3 + 1/(7 + 1/16)', a row per element.
gamma, gammaln, erf, erfc, erfinv, erfcinv, erfcx:
    Python: elfun.py. The SciPy function of the same name: scipy.special.gamma, scipy.special.gammaln, scipy.special.erf, scipy.special.erfc, scipy.special.erfinv, scipy.special.erfcinv, scipy.special.erfcx, element by element. Single stays single; integers are refused.
expint:
    Python: elfun.py. scipy.special.exp1, the exponential integral E1(x); for a negative real x it is -Ei(-x) - i*pi by scipy.special.expi (continued from above the cut), and -Inf - i*pi at -Inf, where SciPy's expi gives NaN.
psi:
    Python: elfun.py. scipy.special.digamma; psi(k, x) is scipy.special.polygamma(k, x).
gammainc, gammaincinv:
    Python: elfun.py. scipy.special.gammainc and scipy.special.gammaincinv, or scipy.special.gammaincc and scipy.special.gammainccinv for 'upper' (SciPy takes the arguments the other way round: gammainc(x, a) here is gammainc(a, x) there); a of 0 gives 1 and 0. The scaled forms, P or Q times gamma(a+1)*exp(x)/x^a, are computed directly: below x = a + 1 by the series sum of x^n/((a+1)...(a+n)), which is the scaled lower one, above it by the continued fraction for Gamma(a, x)*exp(x)/x^a (modified Lentz), times a for the scaled upper one; the other is their sum less the one found, the factor gamma(a+1)*exp(x)/x^a taken from Stirling's series and a*(t - log(1+t)) with x = a(1+t) for a of 30 or more, so that no large logarithms cancel. single in gives single out.
beta, betaln:
    Python: elfun.py. scipy.special.beta and scipy.special.betaln (the logarithm, without overflow), with implicit expansion.
betainc, betaincinv:
    Python: elfun.py. scipy.special.betainc(z, w, x), or scipy.special.betaincc for 'upper', and scipy.special.betaincinv(z, w, y), or scipy.special.betainccinv for 'upper' (not 1 - y, which would lose small values). single in gives single out for betaincinv.
besselj, bessely, besseli, besselk:
    Python: elfun.py. scipy.special.jv, scipy.special.yv, scipy.special.iv and scipy.special.kv, or the scaled scipy.special.jve, scipy.special.yve, scipy.special.ive and scipy.special.kve when the third input is 1. Complex arithmetic is used where the real function is undefined: a negative argument with an order that is not whole, and any negative argument for bessely.
besselh:
    Python: elfun.py. scipy.special.hankel1, or scipy.special.hankel2 for k = 2.
airy:
    Python: elfun.py. scipy.special.airy gives Ai, Ai', Bi and Bi' together; k (0 to 3) picks one. With scale 1, scipy.special.airye of the argument as a complex number: Ai and Ai' times exp(2/3 z^(3/2)) (complex for z below 0), Bi and Bi' times exp(-abs(real(2/3 z^(3/2)))). The second output, an error flag, is 0.
ellipke:
    Python: elfun.py. scipy.special.ellipk and scipy.special.ellipe of the parameter m.
ellipj:
    Python: elfun.py. scipy.special.ellipj(u, m), whose sn, cn and dn are returned. For complex u = x + iy, Jacobi's addition formulas from the functions of x with m and of y with 1 - m (Abramowitz and Stegun 16.21).
legendre:
    Python: elfun.py. scipy.special.lpmv(m, n, x) for each order m = 0..n. That function includes the factor (-1)^m; the 'sch' and 'norm' forms multiply by (-1)^m and by their normalising square roots of factorial ratios.
# ---- elmat.py: making and reshaping arrays ---------------------------------------------------
zeros, ones:
    Python: elmat.py. numpy.full with 0 or 1, in the NumPy type of the class asked for (double unless a class name or 'like' gives another).
Inf, inf, NaN, nan, pi:
    Python: elmat.py. Python's math.inf, math.nan or math.pi; with sizes, numpy.full of that value.
true, false:
    Python: elmat.py. The value True or False; with sizes, a NumPy array of booleans filled with it.
i, j:
    Python: elmat.py. Python's complex number 1j.
eps:
    Python: elmat.py. numpy.finfo(float).eps (2^-52), or that of single (named, or by 'like' and a value); eps(x) is numpy.spacing(abs(x)), the distance from abs(x) to the next larger number of its class, and NaN for Inf and NaN.
realmax, realmin, flintmax:
    Python: elmat.py. numpy.finfo's max and tiny (the largest and the smallest normalised double or single), and 2^53 or 2^24, the largest whole numbers that every smaller whole number is exact below.
intmax, intmin:
    Python: elmat.py. The largest and smallest value of the integer class (int32 unless named, or the class of the value after 'like'), in that class.
eye:
    Python: elmat.py. numpy.eye with the rows and columns asked for, in the class asked for.
rand:
    Python: elmat.py. One generator for the session: NumPy's Mersenne Twister, numpy.random.RandomState, seeded with 5489 by default and by rng. rand draws its random_sample (uniform on [0, 1)) and fills the array down the columns. The old forms rand('state') and rand('seed') give the generator's whole state (its 624 words, position and kept normal, as a column of 627 numbers) without drawing, and rand('state', s) sets it from such a column or reseeds from a number.
randn:
    Python: elmat.py. The standard_normal values of the same Mersenne Twister generator as rand, filling the array down the columns; 'complex' adds an imaginary part drawn the same way.
randi:
    Python: elmat.py. floor(u*(imax - imin + 1)) + imin from the uniform values u of rand's generator, in the class asked for.
randperm:
    Python: elmat.py. n uniform values from rand's generator, and the order that sorts them (numpy.argsort, stable): the first k positions of that order.
rng:
    Python: elmat.py. Seeds the generator of rand, randn and randi: a whole number from 0 to 2^32 - 1 (0 is the default seed, 5489), 'default', or 'shuffle' (the clock in milliseconds). It returns the previous settings as a struct whose State is the generator's whole state, so rng(s) with that struct takes the generator back to where it was.
linspace:
    Python: elmat.py. a + k*(b - a)/(n - 1) for k = 0..n-1 by NumPy, the last point set to b exactly; 100 points unless n is given.
logspace:
    Python: elmat.py. 10.^e for e from linspace(a, b, n) (50 points unless given); a b of pi means up to pi itself.
colon:
    Python: elmat.py and ops.py. The colon operator of the language (a:b, a:d:b), the code that builds ranges in expressions. The number of steps is floor((b - a)/d) with an allowance of three roundings, so 0:0.1:1 has 11 elements. Whole a and d give a + d*k directly; otherwise the first half of the elements counts up from a and the second half down from the last one, which is b itself when it lands within a rounding of it, so both ends are exact. Integer classes take whole steps.
reshape:
    Python: elmat.py. NumPy's reshape in column order (order='F'), so the elements keep their order down the columns; one size may be [] and is then worked out. Cells, structs and text are reshaped the same way.
squeeze:
    Python: elmat.py. The same column-order reshape with the dimensions of size 1 left out (a 2-D array is returned as it is).
permute, ipermute:
    Python: elmat.py. numpy.transpose with the order given (from 1), after trailing dimensions of size 1 are added; ipermute uses the inverse order, from numpy.argsort.
shiftdim:
    Python: elmat.py. permute with the order n+1, ..., N, 1, ..., n (n taken modulo the number of dimensions); for n < 0 a reshape with -n leading dimensions of size 1; with no n, n is the number of leading dimensions of size 1.
repmat:
    Python: elmat.py. numpy.tile of the array, the array first given trailing dimensions of size 1 to match the repetitions.
cat, horzcat, vertcat:
    Python: elmat.py. Along dimensions 1 and 2, the concatenation the brackets [a, b] and [a; b] do, with the same class rules; along a higher dimension, numpy.concatenate after the arrays get the missing dimensions of size 1. Empty [] arrays are left out.
diag:
    Python: elmat.py. numpy.diag: a vector becomes a square matrix with it on diagonal k; a matrix gives its diagonal k as a column.
magic:
    Python: elmat.py. For odd n the Siamese construction (each number placed by moving up and right from the middle of the top row), written as two whole-array formulas; for n a multiple of 4, 1..n^2 in rows with the elements on the diagonals of each 4-by-4 block replaced by n^2 + 1 minus themselves; for other even n, four odd magic squares of size n/2 put together and some columns exchanged (the LUX method).
meshgrid, ndgrid:
    Python: elmat.py. numpy.meshgrid: with xy indexing for meshgrid (x varies along the columns) and ij indexing for ndgrid (the first vector along the first dimension).
sub2ind, ind2sub:
    Python: elmat.py. Linear indices in column order: the sum of (s_k - 1) times the product of the earlier sizes, plus 1; ind2sub takes the remainders and quotients back out. When fewer subscripts than dimensions are given, the last one spans the dimensions left.
find:
    Python: elmat.py. numpy.flatnonzero of the array taken down its columns; rows and columns from the remainder and quotient by the number of rows; find(x, k, 'last') keeps the last k. Nothing found in a scalar or a 0-by-0 array gives 0-by-0 results.
nnz:
    Python: elmat.py. numpy.count_nonzero; for a sparse matrix, SciPy's count of stored values.
fliplr, flipud, flip:
    Python: elmat.py. NumPy's reversed slicing a[:, ::-1] and a[::-1], or numpy.flip along a dimension (the first one whose size is not 1 unless given).
rot90:
    Python: elmat.py. numpy.rot90, k quarter turns counterclockwise.
circshift:
    Python: elmat.py. numpy.roll by the shifts given, along the first dimension whose size is not 1 (or the dimension given, or dimension by dimension for a vector of shifts).
tril, triu:
    Python: elmat.py. numpy.tril and numpy.triu with the diagonal offset k.
pagemtimes:
    Python: matfun.py. Both arrays' first two dimensions moved last (numpy.moveaxis), turned (and conjugated) as asked, and multiplied by numpy.matmul, which takes the pages of size 1 against all of the other's; the result's first two dimensions moved back.
pagetranspose, pagectranspose:
    Python: matfun.py. permute(A, [2 1 3 ...]), so any class keeps its class (and conj for pagectranspose).
tensorprod:
    Python: matfun.py. numpy.tensordot over the dimensions given (numbered from 1, missing trailing ones added as 1), or axes=0 for the outer product; 'all' sums A.*B. Trailing dimensions of size 1 are dropped from the result.
kron:
    Python: elmat.py. numpy.kron, the Kronecker product.
blkdiag:
    Python: elmat.py. scipy.linalg.block_diag.
toeplitz, hankel:
    Python: elmat.py. scipy.linalg.toeplitz (with conj(c) as the row when only c is given) and scipy.linalg.hankel.
vander:
    Python: elmat.py. numpy.vander: the columns are the powers of v from n - 1 down to 0.
hilb, invhilb:
    Python: elmat.py. 1./(i + j - 1) by NumPy; scipy.linalg.invhilbert, the exact inverse.
pascal:
    Python: elmat.py. scipy.linalg.pascal, the symmetric Pascal matrix.
compan:
    Python: elmat.py. scipy.linalg.companion of the polynomial's coefficients.
wilkinson:
    Python: elmat.py. abs(-m:m) on the diagonal (m = (n - 1)/2) and ones next to it, by numpy.diag.
rosser:
    Python: elmat.py. Rosser's 8-by-8 test matrix, written out.
accumarray:
    Python: elmat.py. Subscripts (a matrix, a column of linear indices, or a cell of index vectors) are turned into linear indices (numpy.ravel_multi_index in column order) and the values summed into them with numpy.add.at; places nothing went to get the fill value. With a function, the values of each place are gathered in the order they come and the function called once for each place; logical or cell results make a logical or cell array (no place at all gives doubles).
double, single, logical, int8, uint8, int16, uint16, int32, uint32, int64, uint64:
    Python: elmat.py. NumPy's astype to the class's type. To an integer class, a value is rounded to the nearest whole number with halves away from zero (by truncating and looking at the fraction, which is exact; adding 0.5 would itself round past 2^52), NaN becomes 0, and values beyond the class's range saturate at its ends; an integer value converts exactly, without a round trip through doubles (int64 and uint64 hold more than a double can). logical refuses NaN and complex values. double of a string array reads each string as a number (NaN where it is not one). Of a Python object: pycall.py, NumPy's asarray (double), the items, str() or the dict's items.
cast:
    Python: elmat.py. The conversion of double, single, logical or the integer classes to the class named, or to the class of a 'like' value; 'char' goes through char.
typecast:
    Python: elmat.py. NumPy's view: the same bytes read as another type, with no conversion, so typecast(single(1), 'uint32') is 1065353216.
# ---- datafun.py: data analysis -----------------------------------------------------------------
sum, prod:
    Python: datafun.py. numpy.sum and numpy.prod along the first dimension whose size is not 1, or the dimension given ('all': every element, a vector of dimensions: those). Integers, logical and char are summed in doubles; an integer or single input gives its own class (integers saturate) unless 'double' is asked, and logical and char give double. 'omitnan' puts 0 (or 1 for prod) in place of NaN first.
cumsum, cumprod:
    Python: datafun.py. numpy.cumsum and numpy.cumprod along the first dimension whose size is not 1 or the one given; 'reverse' flips the array, accumulates and flips back; 'omitnan' puts 0 (or 1) in place of NaN. Integer classes are accumulated in doubles and returned in their class.
cummax, cummin:
    Python: datafun.py. numpy.maximum.accumulate and numpy.minimum.accumulate along the dimension. NaN is passed over (taken as -Inf or Inf) except where only NaN has been seen so far, which stays NaN; 'includenan' lets a NaN carry forward.
diff:
    Python: datafun.py. numpy.diff along the first dimension whose size is not 1 or the one given, n times for diff(x, n); a dimension that runs out gives an empty array.
mean:
    Python: datafun.py. The values along the dimension (or vecdim, or all) gathered into rows and summed in double with their weights ('Weights', else 1), divided by the sum of the weights; 'omitnan' drops NaN values and their weights, and an empty slice gives NaN. Integers, logical and char give double unless 'native'; single stays single unless 'double'. A probability distribution object gives its own mean.
median:
    Python: datafun.py. numpy.median of each row of the gathered values (NaN left out with 'omitnan', else a NaN gives NaN; an empty slice gives NaN); complex values are ordered by abs, then angle (numpy.lexsort). Integers are rounded back to their class and logicals stay logical unless 'default' or 'double' is given; single stays single. A probability distribution object gives its own median.
mode:
    Python: datafun.py. numpy.unique with counts for each row of the values gathered along the dimension (or vecdim, or all), NaN left out: the most frequent value, the smallest of those tied, in the class of A. The second output is the frequency and the third a cell with all the tied values; an empty slice gives NaN, 0 and an empty cell.
var, std:
    Python: datafun.py. The values along the dimension (or the dimensions of vecdim, or all) are gathered into rows; the mean is the weighted sum over the sum of the weights (1 each unless w is a vector along the dimension or an array the size of A), and the variance the weighted sum of squared distances from it, divided by n - 1 (w = 0), by n (w = 1) or by the sum of the weights. 'omitnan' drops NaN values and their weights. A single element gives 0 (NaN if it is not finite). std is the square root; the second output is the mean. A probability distribution object gives its own.
range:
    Python: datafun.py. max(A, [], ...) minus min(A, [], ...) by the code of min and max (NaN left out unless 'includenan'), along a dimension, a vector of them or 'all'; the class is kept.
max, min:
    Python: datafun.py. Along a dimension, numpy.argmax or numpy.argmin pick the position: NaN is left out (taken as -Inf or Inf) unless 'includenan', and a column of NaN gives NaN; complex values compare by magnitude; the second output is the position from 1 (or the linear index with 'linear'). With two arrays, numpy.fmax and numpy.fmin element by element (numpy.maximum and numpy.minimum with 'includenan'), and for complex values by magnitude and then angle. Two scalars compare directly.
bounds:
    Python: datafun.py. min(A, [], ...) and max(A, [], ...) by the code of min and max, with the dimension, a vector of them, 'all' and the NaN flag passed on.
any, all:
    Python: datafun.py. numpy.any and numpy.all of x ~= 0 along the first dimension whose size is not 1 or the one given; NaN does not count as true for any. A vector gives one logical.
xor, not, and, or:
    Python: datafun.py and ops.py. The language's logical operators: the code that runs xor, ~a, a & b and a | b in expressions, with implicit expansion; and(a, b, ...) and or(a, b, ...) take any number of arguments, left to right.
sort:
    Python: datafun.py. A stable sort of each vector along the dimension (numpy.argsort with kind 'stable', so equal values keep their order): NaN goes last ascending and first descending, complex values sort by magnitude and then angle (numpy.lexsort), and the second output is the order from 1. Cells of text and string arrays sort in Python by the characters' codes.
sortrows:
    Python: datafun.py and tables.py. One stable sort per column, from the last column named to the first, so the first column given decides first; a negative column number sorts that column descending. Cells are sorted in Python, text against text and numbers against numbers. A table is sorted the same way by its variables, each row of a variable as a Python tuple, missing values last going up and first going down.
issorted:
    Python: datafun.py. True when each element is no larger than the next (complex values by magnitude).
unique:
    Python: datafun.py. numpy.unique with its first indices and the inverse map, giving C, ia and ic; every NaN counts as a distinct value and they come last; complex values are ordered by magnitude, then angle. 'stable' reorders C by first appearance; 'last' takes the last index; 'rows' compares rows as tuples in Python. Text in cells and string arrays is handled in Python, sorted by the characters' codes, and graphics objects by their handle numbers, coming back as objects.
ismember:
    Python: datafun.py and tables.py. numpy.isin for the logical result; the locations come from a Python dictionary of each value's first position in s. Text and 'rows' compare in Python as strings and tuples, graphics objects by their handle numbers, tables by each row's values as a tuple.
union, intersect, setdiff, setxor:
    Python: datafun.py. The elements become Python lists and their first positions a dictionary; the result is the union, intersection, difference or symmetric difference of their sets, sorted (complex values by magnitude and angle) or, with 'stable', in the order the values first appear. ia and ib point to the first occurrences. Text and 'rows' work the same way on strings and row tuples, and graphics objects by their handle numbers, coming back as objects.
histcounts:
    Python: datafun.py. With no edges given, a bin width is chosen by Scott's rule, 3.5*std(x)/n^(1/3), and rounded to 1, 2 or 5 times a power of ten (at most 1000 bins), with the edges on its multiples; a number of bins gets a round width too, or exact limits when a round one cannot cover the data. Each value goes to the bin [e(k), e(k+1)) found by numpy.searchsorted, the last bin closed on the right, and numpy.bincount counts them. The normalisations divide by the number of values or the bin widths, or add up with numpy.cumsum.
histc:
    Python: datafun.py. numpy.searchsorted of each value into the edges: bin k holds edges(k) <= x < edges(k+1), and the last bin the values equal to edges(end); numpy.bincount counts them.
discretize:
    Python: datafun.py. numpy.searchsorted into the edges, the last bin closed on the right; values outside the edges and NaN give NaN.
cov:
    Python: datafun.py. Its own: the columns centred on their means and multiplied, (X - mean)'*(Y - mean), divided by n - 1 (by n when w is 1, or when there is one observation), or with weights about the weighted mean, divided by their sum. cov(A, B) puts A(:) and B(:) in two columns; a second input of 0 or 1 is the normalization unless there is a third. 'omitrows' drops rows with NaN; 'partialrows' takes each pair from the rows both have. single in gives single out.
corrcoef:
    Python: datafun.py. numpy.corrcoef with the variables in columns. The p-values test each correlation with the t statistic r*sqrt((n - 2)/(1 - r^2)) and two tails of scipy.stats.t.
trapz:
    Python: datafun.py. The trapezoidal rule along the first dimension whose size is not 1 or the one given: the sum of each step's width times the mean of the values at its ends. The widths are 1, a scalar spacing, the differences of the points x, or those of an array x the size of y.
cumtrapz:
    Python: datafun.py. The trapezoidal rule's running sum, from 0, along the first dimension whose size is not 1 or the one given; the widths as for trapz.
quantile, prctile:
    Python: datafun.py. For each row of the values gathered along the dimension (or vecdim, or all) the values are sorted (NaN left out) and placed at the probabilities (i - 0.5)/n; numpy.interp interpolates linearly between them, and p below the first or above the last gives the smallest or largest value. The quantiles take the place of the first dimension; a vector's are laid out as p is. quantile(x, n) asks for the probabilities (1:n)/(n + 1); prctile divides p by 100, and iqr is the difference of the 75th and 25th.
iqr:
    Python: datafun.py. The difference of the 0.75 and 0.25 quantiles, computed as quantile computes them. A probability distribution object gives its own.
skewness, kurtosis:
    Python: datafun.py. For each vector along the dimension (a vector of them, or 'all'), with NaN left out: the central moments m2, m3 and m4 by NumPy, then m3/m2^1.5 or m4/m2^2 (a normal sample gives about 3); flag 0 corrects the bias, sqrt(n(n-1))/(n-2) for the skewness and the standard formula for the kurtosis (NaN for too few values). single is computed in single.
rescale:
    Python: datafun.py. l + (x - inmin)./(inmax - inmin).*(u - l), x first clamped to [inmin, inmax] (its least and greatest unless 'InputMin' and 'InputMax' are given); l, u and the bounds broadcast against x as arrays; a constant x gives l. single stays single.
normalize:
    Python: datafun.py. N = (A - C)./S along a dimension, C and S computed by NumPy with NaN left out of them (nanmean, nanmedian, sums over the values that are not NaN): 'zscore' with the mean and the standard deviation (n - 1), or 'robust' with the median and the median absolute deviation; 'norm' p dividing by the p-norm (the largest |x| for Inf); 'range' [a b] from the least and greatest; 'medianiqr' with the median and the interquartile range (quantiles at (i - 0.5)/n, linear between); 'center' and 'scale' given apart or together, as values or by name ('first' is the first element). C and S are the second and third outputs (0 and 1 when not used). single stays single.
movmean, movsum, movprod, movmax, movmin, movmedian, movmad, movstd, movvar:
    Python: datafun.py. For each position along the dimension, NumPy's mean, sum, prod, max, min or median of the window around it, the median of the absolute deviations from its median (movmad), or the standard deviation and variance normalized by n - 1 (by n for a weight of 1, or a window of one value). The window is k elements centred (for an even k, one more before than after) or [kb kf] before and after, worked over all the other dimensions at once. 'omitnan' uses NumPy's nan- versions; Endpoints 'shrink' shortens the windows at the ends, 'discard' drops those positions, 'fill' or a number sets them.
# ---- matfun.py: linear algebra -----------------------------------------------------------------
inv:
    Python: matfun.py and sparse.py. A sparse matrix: SuperLU's factors (scipy.sparse.linalg.splu) solve for each column of the identity, the result stored sparse; a singular one gives Inf with the singular-matrix warning. A full one: a scalar's inverse is 1/x (so inv(-0) is -Inf and inv(Inf) is 0). Otherwise numpy.linalg.inv, after an LU factorisation (scipy.linalg.lu_factor) gives LAPACK's estimate of the reciprocal condition number (its gecon routine, in the 1-norm): a zero pivot gives Inf and the singular-matrix warning, an estimate below eps the close-to-singular warning, and NaN or Inf in the matrix a matrix of NaN. single stays single. Of a model: control.py, the inverse realization.
det:
    Python: matfun.py and sparse.py. numpy.linalg.det: the product of the pivots of an LU factorisation with partial pivoting; det([]) is 1. A sparse matrix: the product of the diagonal of SuperLU's U (scipy.sparse.linalg.splu) times the signs of its row and column permutations, 0 when the factorisation finds it singular.
trace:
    Python: matfun.py. numpy.trace, the sum of the diagonal of a square matrix.
rank:
    Python: matfun.py. The number of singular values (numpy.linalg.svd, values only) above the tolerance max(size(A))*eps(max(s)), or the one given.
norm:
    Python: matfun.py and sparse.py. A sparse matrix: the 1-norm, Inf-norm and 'fro' from the stored values (column sums, row sums, the root of the sum of squares), the 2-norm by numpy.linalg.norm of the full matrix up to 200 rows or columns and by scipy.sparse.linalg.svds (the largest singular value) beyond; a sparse vector's p-norms from its stored values. A full one: for a vector, numpy.linalg.norm with p (max(abs(v)) for Inf, the smallest for -Inf, the count of nonzeros for 0). For a matrix: the 2-norm is the largest singular value (numpy.linalg.svd), the 1-norm the largest column sum of abs(A), Inf the largest row sum, and 'fro' the 2-norm of all the elements. Of a model: control.py, the H2 norm from the controllability Gramian, the H-infinity norm as getPeakGain finds it.
vecnorm:
    Python: matfun.py. sum(abs(A).^p).^(1/p) along the first dimension whose size is not 1 or the one given, or max(abs(A)) for p = Inf.
cond:
    Python: matfun.py. The ratio of the largest to the smallest singular value (numpy.linalg.svd) for the 2-norm, Inf when the smallest is 0; numpy.linalg.cond for the 1, Inf and 'fro' norms.
rcond:
    Python: matfun.py. LAPACK's estimate of the reciprocal condition number in the 1-norm (its gecon routine, by scipy.linalg.lapack.get_lapack_funcs) from an LU factorisation by scipy.linalg.lu_factor; 0 when the factorisation fails.
condest:
    Python: matfun.py and sparse.py. For a full matrix, numpy.linalg.cond in the 1-norm, computed exactly rather than estimated. For a sparse one, norm(S, 1) times scipy.sparse.linalg.onenormest of the inverse, applied through SuperLU's factors (scipy.sparse.linalg.splu); Inf when they cannot be made.
eig:
    Python: matfun.py. A matrix equal to its conjugate transpose goes to numpy.linalg.eigh (numpy.linalg.eigvalsh for the values alone), which gives real values in increasing order and orthonormal vectors; any other to numpy.linalg.eig, and eig(A, B) to scipy.linalg.eig. The third output, the left vectors, comes from scipy.linalg.eig with left=True. 'vector' returns the values as a column. NaN or Inf in A is refused.
eigs:
    Python: sparse.py. Up to 600 rows (or when k is n - 1 or more) every eigenvalue by scipy.linalg.eig (with B, the generalized problem), of which the k (6 unless given) that sigma picks are kept, the vectors scaled to norm 1. Larger matrices go to ARPACK: scipy.sparse.linalg.eigsh when A is symmetric and real, scipy.sparse.linalg.eigs otherwise, with which 'LM', 'LR' (or 'LA'), 'SR' (or 'SA'), 'LI' or 'SI', and shift-invert about sigma for 'smallestabs' (sigma 0) or a number (a sigma that is an eigenvalue is moved by 1e-10 relative). A function handle is wrapped as a scipy.sparse.linalg.LinearOperator: A*x, or (A - sigma*I)\x as ARPACK's OPinv. flag is 1 when ARPACK stops before all k converge (its converged values are returned).
svd:
    Python: matfun.py. numpy.linalg.svd: the singular values alone as a column, or U, S and V with S placed in a matrix of A's size; 'econ' (and svd(A, 0) for a tall A) keeps only min(m, n) of them. NaN or Inf is refused.
svds:
    Python: sparse.py. Up to 600 columns or rows (or when k is that number less 1 or more) the full numpy.linalg.svd, of which the k (6 unless given) that sigma picks are kept: the largest, the smallest, the smallest above max(m, n)*eps times the largest ('smallestnz'), or those nearest a number. Larger matrices go to ARPACK: scipy.sparse.linalg.svds with which 'LM' or 'SM', or for a number the eigenvalues of [0 A; A' 0] nearest it (scipy.sparse.linalg.eigsh, shift-invert), whose positive ones are the singular values.
qr:
    Python: matfun.py. scipy.linalg.qr: R alone (upper triangular), Q and R, or with three outputs the factorisation with column pivoting (A(:, p) = Q*R), its permutation a matrix, or a vector with 'vector' or 0; 'econ' (or 0) gives the economy size. qr(A, B) gives Q'*B in place of Q. An empty A gives an identity Q and an empty R; single stays single.
lu:
    Python: matfun.py and sparse.py. scipy.linalg.lu (partial pivoting): with two outputs the permuted L and U, with three L, U and the permutation matrix P (or a vector with 'vector'); with one output the two factors in one matrix. A square sparse matrix goes to SuperLU (scipy.sparse.linalg.splu): with up to three outputs with no column ordering and diag_pivot_thresh 1 (partial pivoting), with four with its COLAMD column ordering, P*S*Q = L*U; the factors sparse. A singular or rectangular sparse matrix uses scipy.linalg.lu, its factors stored sparse.
chol:
    Python: matfun.py. numpy.linalg.cholesky gives the lower factor L, returned as R = L' (or L for 'lower'). When A is not positive definite, the second output p is one more than the size of the largest leading block that is, and the factor of that block is returned; with one output it is an error.
schur:
    Python: matfun.py. scipy.linalg.schur: the real Schur form (quasi-triangular) for a real matrix and the complex one for a complex matrix, or the kind asked; two outputs give U and T.
hess:
    Python: matfun.py. scipy.linalg.hessenberg with the orthogonal Q: A = Q*H*Q'.
pinv:
    Python: matfun.py. From numpy.linalg.svd: V(:, 1:r)*diag(1./s(1:r))*U(:, 1:r)', with r the number of singular values above max(size(A))*eps(max(s)) or the tolerance given.
null:
    Python: matfun.py. The last columns of V from numpy.linalg.svd, those of the singular values at or below max(size(A))*eps(max(s)): an orthonormal basis. null(A, 'r') builds a rational basis from the reduced row echelon form (the pivot-free columns set to 1 in turn).
orth:
    Python: matfun.py. The first columns of U from numpy.linalg.svd, one for each singular value above max(size(A))*eps(max(s)).
rref:
    Python: matfun.py. Gauss-Jordan elimination in Python, column by column: the largest remaining element is brought up as the pivot (partial pivoting), its row divided by it, and the column cleared above and below; a column whose largest element is below the tolerance max(size(A))*eps*norm(A, Inf) is set to zero. The second output lists the pivot columns.
expm, logm, sqrtm:
    Python: matfun.py. scipy.linalg.expm (scaling and squaring with a Pade approximant), scipy.linalg.logm and scipy.linalg.sqrtm (both by the Schur form). A sparse matrix: scipy.sparse.linalg.expm, its result sparse; logm and sqrtm of the full matrix, stored sparse.
funm:
    Python: matfun.py. scipy.linalg.funm (the Schur-Parlett method), with NumPy's function for the named ones (exp, log, sin, cos, sqrt, sinh, cosh) and otherwise the function given, called on the arrays SciPy passes.
cross:
    Python: matfun.py. numpy.cross along the first dimension of size 3, or the one given.
dot:
    Python: matfun.py. sum(conj(a).*b): of the whole vectors for two vectors, else along the first dimension whose size is not 1 or the one given.
linsolve:
    Python: matfun.py and ops.py. The code of A\B (see mldivide); the second output is the reciprocal condition estimate for a square A and the rank for another.
balance:
    Python: matfun.py. scipy.linalg.matrix_balance: a diagonal similarity with powers of 2 that makes rows and columns of comparable norm; T is the transformation.
givens:
    Python: matfun.py. With r = hypot(x, y), c = x/r and s = y/r, the rotation [c s; -s c].
planerot:
    Python: matfun.py. The rotation from givens of the vector's two elements, and the rotated vector.
plus, minus, times, rdivide, ldivide, power, eq, ne, lt, le, gt, ge:
    Python: matfun.py and ops.py. The element-wise operator (+, -, .*, ./, .\, .^, ==, ~=, <, <=, >, >=) as the expressions run it: NumPy's add, subtract, multiply, true_divide, power and comparisons with implicit expansion, the class of the result by the language's rules (integers saturate, single wins over double; int64 and uint64 past 2^26 are added, subtracted, multiplied and divided exactly as Python fractions, rounded half away from zero and saturated, since a double cannot hold them), and .^ going to complex arithmetic where a negative number has a fractional power. plus and times take more than two arguments, left to right.
mtimes:
    Python: matfun.py and ops.py. The operator *: a scalar times an array element by element, two matrices by NumPy's matrix product (@), in single when either is single; integer matrices are refused.
mldivide, mrdivide:
    Python: matfun.py and ops.py. The operators \ and /, with A/B solved as (B'\A')'. A square triangular A is solved by back or forward substitution (scipy.linalg.solve_triangular); any other square A by an LU factorisation with partial pivoting (scipy.linalg.lu_factor and scipy.linalg.lu_solve), with LAPACK's condition estimate behind the singular and close-to-singular warnings. A rectangular A gets a least-squares solution from a QR factorisation with column pivoting (scipy.linalg.qr): the basic solution with as many nonzeros as the numerical rank, with a warning when that is below full rank. NaN or Inf in A gives NaN.
mpower:
    Python: matfun.py and ops.py. The operator ^: a whole power by numpy.linalg.matrix_power (repeated squaring), a negative one of the inverse (A\eye); another power by scipy.linalg.fractional_matrix_power; a scalar to a matrix power by scipy.linalg.expm(log(s)*B).
uminus, uplus, transpose, ctranspose:
    Python: matfun.py and ops.py. The operators -a, +a, a.' and a': negation (integers through doubles and back, so -int8(-128) saturates; int64 and uint64 in their own integers, -intmin('int64') saturating to intmax), and NumPy's transpose, with the complex conjugate for '.
# ---- classdef.py, classfun.py, uiapp.py and appfun.py: classes and apps -----------------------------------------------------------
properties, methods, ismethod:
    Python: classfun.py and classdef.py. The class's tables of properties (public ones, its superclasses' first) and methods, made when its classdef file was read.
addlistener, listener, notify:
    Python: classfun.py. A listener kept with the object under the event's name; notify calls each enabled one's callback with the object and the event data (a struct with Source and EventName and the fields given).
plabSuperCall:
    Python: classfun.py and classdef.py. The superclass's constructor run on the same object (handle and the built-in bases have none), or its method found by name and called.
uifigure:
    Python: appfun.py. A figure of a class of its own with the uifigure properties, a number below zero (as a dialog's window has: no number title, never the current figure) and HandleVisibility 'off'.
uibutton, uilabel, uieditfield, uitextarea, uidropdown, uilistbox, uicheckbox, uiswitch, uislider, uispinner, uiknob, uigauge, uilamp, uiradiobutton, uitogglebutton, uiimage, uihyperlink:
    Python: appfun.py and uiapp.py. A component object of the kind's class (uiapp.py makes one for each kind, with its properties and defaults), its Value checked as it is set (numbers within Limits, items among Items or ItemsData). The page draws it from its description (pylab-ui.js: HTML controls; knobs and gauges as SVG) and reports pushes and values; a value taken sets Value and queues the callback with the event data (Value and PreviousValue; ValueChanging while dragging or typing).
uigridlayout:
    Python: uiapp.py and uiobjects.py. Before the figure is described to the page, each grid lays out its children: fixed rows and columns in pixels, 'fit' ones at their content's height (22 pixels), the rest sharing what is left by their weights, less Padding and the spacings; a child's Position becomes its cell (an axes' less a margin for its labels).
uiaxes:
    Python: appfun.py. Axes in pixels inside the app's window or container, drawn on the window's canvas at their container's place.
uialert, uiconfirm, uiprogressdlg:
    Python: appfun.py. msgbox's window, questdlg's question, and waitbar's bar with the Value and Message set.
createCallbackFcn, registerApp, runStartupFcn:
    Python: classfun.py. A callback that calls the app's method with the app (and the event data); a DeleteFcn on the window that deletes the app; the startup method called with the app.
appdesigner:
    Python: iofun.py (it tells the page) and pylab-designer.js. The layout is kept as JSON in a comment at the end of the class file; writing the class takes the callbacks' code from the file as it is (from its Editor tab when it is open there, saved or not), so what was written in the Editor stays; a save puts the new class into that Editor tab too.

# ---- mapping.py and mapproj.py: mapping -----------------------------------------------------------------------------------
deg2km, km2deg, deg2nm, nm2deg, deg2sm, sm2deg, km2nm, nm2km, km2sm, sm2km, nm2sm, sm2nm, km2rad, rad2km, unitsratio, earthRadius:
    Python: mapping.py. Arc length = radius times the angle in radians, the radius 6371 km unless given (a body's mean radius by name); a nautical mile is 1852 m, a statute mile 1609.344 m, a foot 0.3048 m and a survey foot 1200/3937 m.
dms2degrees, degrees2dms, dm2degrees, degrees2dm:
    Python: mapping.py. Sums of the parts over 60 and 3600, the sign taken from the first part that is not zero; the split back takes the whole degrees and minutes of the absolute value.
wrapTo180, wrapTo360, wrapToPi, wrapTo2Pi:
    Python: mapping.py. NumPy's mod of the angle shifted by half a turn; values already within the range are left as they are, and a positive multiple of a full turn stays a full turn.
referenceEllipsoid, wgs84Ellipsoid, referenceSphere:
    Python: mapping.py and mapproj.py. A table of semimajor axes and inverse flattenings (WGS 84 6378137 m and 298.257223563, ...) and of bodies' mean radii; the semiminor axis a*sqrt(1 - e^2), the third flattening f/(2 - f), the mean radius (2a + b)/3, the surface 2*pi*a^2*(1 + (1 - e^2)/e*atanh(e)).
distance, azimuth, reckon:
    Python: mapping.py and mapproj.py. On a sphere the haversine formula and the spherical direct problem; on an ellipsoid Vincenty's iterations for the inverse and direct problems (to 1e-12 radians; where the inverse does not converge, nearly antipodal points, the great circle on the authalic sphere). Rhumb lines from the isometric latitude and the meridian arc (a series in e^2 to e^6).
track2, track1, gcwaypts, interpm:
    Python: mapping.py. Points at equal fractions of the distance along the path, by the direct problem from the start with its azimuth.
meridianarc:
    Python: mapproj.py. The meridian arc by its series in e^2 to e^6.
antipode:
    Python: mapping.py. The latitude negated and the longitude half a turn on, wrapped.
areaint:
    Python: mapping.py. Each part's spherical excess, 2*pi less the sum of the turning angles at its vertices (great-circle edges, the angles from the cross products of the tangent vectors), the smaller of it and the rest of the sphere; with an ellipsoid times the area of its authalic sphere.
areaquad:
    Python: mapping.py. (sin(lat2) - sin(lat1))*(lon2 - lon1) over 4*pi; on an ellipsoid with Snyder's q in place of 2*sin(lat).
geodetic2ecef, ecef2geodetic, geodetic2enu, enu2geodetic, geodetic2ned, ned2geodetic, geodetic2aer, aer2geodetic, ecef2enu, enu2ecef, ecef2ned, ned2ecef, ecef2aer, aer2ecef, enu2aer, aer2enu, ned2aer, aer2ned:
    Python: mapping.py and mapproj.py. ECEF from the prime vertical radius N = a/sqrt(1 - e^2*sin(lat)^2); back by Bowring's iteration from his first guess. The local frames rotate the ECEF difference from the origin by its latitude and longitude; AER from ENU by atan2 and hypot.
inpolygon, polyarea, ispolycw, poly2cw, poly2ccw, polysplit, polyjoin, polyxpoly:
    Python: mapping.py. The crossing count of a ray from each point (even-odd, so holes count) and a collinearity test for the edge; the shoelace formula for the area and its sign for the direction; each segment of one line against each of the other for the crossings.
projcrs, geocrs, projfwd, projinv:
    Python: mapping.py and mapproj.py. A table of EPSG codes with their projections, ellipsoids and parameters (UTM, SWEREF99, RT90, LAEA and LCC Europe, Lambert-93, British National Grid, Conus Albers, Mercator, UPS); the projections in NumPy: the transverse Mercator by Krüger's series to the fourth power of the third flattening, the others from Snyder's formulas on the ellipsoid (Mercator, Lambert conformal conic, Albers, Lambert azimuthal equal-area, polar stereographic) or the sphere. Other codes go to pyproj (PROJ) when Pyodide can load it.
axesm, worldmap, setm, getm, gcm, defaultm, ismap, framem, gridm, mlabel, plabel, tightmap, showaxes, mfwdtran, minvtran:
    Python: mapping.py and mapproj.py. Map axes are ordinary axes, hidden and of equal aspect, with their projection kept beside them. The frame is the boundary of the latitude and longitude limits (a circle about the origin for the azimuthal projections) projected; the graticule meridians and parallels at the line locations; the labels text at the frame's edges. worldmap chooses Robinson for the world, a polar stereographic for a polar cap, an equidistant conic or transverse Mercator for a region, by its extent.
plotm, linem, scatterm, textm, patchm, fillm, surfm, pcolorm, contourm:
    Python: mapping.py. The points projected; outside the map limits (or beyond the frame's circle, or on the far side of an orthographic globe) left out as NaN, and lines broken where the longitude jumps across the map's edge; then plot, line, scatter, text, patch or surface. contourm projects contourc's lines of the latitude and longitude grid.
geoshow, mapshow:
    Python: mapping.py. Each feature by its Geometry (point markers, lines, a polygon as one patch whose rings the page fills even-odd, so that holes stay open), projected on map axes; a raster as a surface at the cell centres its reference gives.
geoaxes, geoplot, geoscatter, geobubble, geolimits:
    Python: mapping.py. Axes with longitude as x and latitude as y, marked geographic so that the page labels their ticks in degrees with E, W, N or S, the aspect 1 : cos(middle latitude); plot, scatter and bubblechart draw in them.
geobasemap, addCustomBasemap, removeCustomBasemap:
    Python: mapping.py keeps the basemap's name (and a custom one's tile address, attribution and deepest zoom level) with the axes; the page draws it (pylab-basemap.js). For map tiles: the zoom level whose tiles have about as many pixels a degree as the screen, fewer if the view would need more than 64 tiles; the tiles over the view fetched as images with CORS (so that the figure can still be saved) and kept for the session, up to 600; each drawn into the axes' longitude and latitude in strips of rows, since Web Mercator's rows are not evenly spaced in latitude (y = 1/2 - ln((1 + sin(lat))/(1 - sin(lat)))/(4*pi)), all into one picture of the axes' box. streets-light and streets-dark are OpenStreetMap's tiles turned to greys, the water told by its blue. darkwater, grayland and bluegreen fill Natural Earth's land and then its lakes (1:110m for views wider than 90 degrees, else 1:50m) on the water's colour, with copies 360 degrees apart past the antimeridian. A saved picture or file first waits (up to 20 s) for what is still loading.
georefcells, georefpostings, georasterref, maprefcells, maprefpostings, geographicToIntrinsic, worldToIntrinsic, geointerp:
    Python: mapping.py. The limits, size and interpretation (cells or postings) of a raster; intrinsic coordinates are the fraction of the limits times the size (from 0.5 for cells, 1 for postings); geointerp is scipy.ndimage.map_coordinates at them.
shaperead, shapeinfo, shapewrite:
    Python: mapping.py. PyLAB's own reader and writer of the shapefile layout: the 100-byte header (file code 9994, big-endian lengths, little-endian shape type and bounding box), records of points, multipoints, polylines and polygons (with their part indices), the .shx index, and the dBASE III table of attributes (numbers, text and logicals). Record lengths are checked against the file.
    landareas, worldlakes, worldrivers and worldcities, when no such file is found: geodata.py fetches Natural Earth's GeoJSON (pyfetch, once a session) and turns its features into the same records, polygons' outer rings clockwise and holes anticlockwise (by the sign of the shoelace area), the name attribute as Name.
readgeoraster, geotiffread, geotiffinfo:
    Python: mapping.py. The TIFF read by Pillow (loaded by Pyodide the first time); the GeoTIFF tags ModelPixelScale (33550), ModelTiepoint (33922) and the GeoKeyDirectory (34735: geographic or projected, pixel is area or point, the projected system's EPSG code) give the raster reference.

# ---- symmath.py and symbolic.py: symbolic math on SymPy --------------------------------------------------------
sym, syms:
    Python: symbolic.py and symmath.py. A symbolic value holds a 2-D array of SymPy expressions (a symbolic function also its arguments). The first one made imports SymPy, which Pyodide loads then. Each name's current sympy.Symbol is kept with its assumptions (complex unless real, positive, integer or rational is given), and expressions are brought up to date with it before they are worked on. A double is matched against p/q (fractions.Fraction.limit_denominator), p*pi/q and sqrt(p)/q, kept when it is that double exactly, else taken as its binary fraction. The operators, indexing, concatenation and display reach SymPy through hooks in ops.py, index.py and display.py; a function that numbers have too (sin, diff, sum, det, ...) hands a symbolic argument to symmath.py.
str2sym:
    Python: symbolic.py. The text's operators and function names translated to SymPy's (^ to **, ~= to !=, 2i to 2*I, ...) and read by sympy.parsing.sympy_parser.parse_expr, every other name a symbol; a single ==, ~=, <, <=, > or >= makes an equation or inequality.
symfun, argnames, formula:
    Python: symmath.py. A symbolic function is its formula and its argument symbols; a call substitutes the arguments (element by element for arrays) with SymPy's subs.
vpa, digits:
    Python: symmath.py. SymPy's evalf to digits significant digits (32 unless set), of the number as sym recognizes it.
poly2sym, sym2poly:
    Python: symmath.py. The sum of c(i)*x^(n-i); sympy.Poly's all_coeffs, converted to doubles.
piecewise:
    Python: symmath.py. sympy.Piecewise of the values and conditions in order, NaN when none holds.
int:
    Python: symmath.py. sympy.integrate, for each element; a definite integral with conds='none' (no conditions on the parameters). 'Hold' keeps an unevaluated sympy.Integral.
limit:
    Python: symmath.py. sympy.limit with dir '+-' (both sides, NaN when they differ), '-' for 'left' and '+' for 'right'.
taylor, series:
    Python: symmath.py. sympy.series about the point to the order given (6 unless given), without its O(...) term. Of models: control.py, their product.
symsum, symprod:
    Python: symmath.py. sympy.summation and sympy.product over k from a to b (from 0 to k-1 for the indefinite sum).
jacobian, hessian, divergence, curl, laplacian:
    Python: symmath.py. sympy.Matrix's jacobian and sympy.hessian; the others from sympy.diff of each component. divergence and curl of arrays on a grid take the differences gradient takes along x (the columns), y (the rows) and z; curl's angular velocity is half the curl along the flow (in 2-D, half of curlz). laplacian of a graph: graphs.py, the degree matrix less the adjacency matrix (ones, the diagonal cleared).
simplify, simplifyFraction:
    Python: symmath.py. sympy.simplify, after expand_log, powdenest and logcombine with force=True for 'IgnoreAnalyticConstraints'; simplifyFraction is sympy.cancel of sympy.together. simplify of a graph: graphs.py, the first edge of each pair kept with the weights combined.
expand, collect, combine, horner:
    Python: symmath.py. sympy.expand with trig=True (multinomial and mul alone for 'ArithmeticOnly'); sympy.collect of the expanded expression; combine by sympy.powsimp, sympy.logcombine, sympy.gammasimp or the product-to-sum rule TR8 of sympy.simplify.fu for 'sincos'; sympy.horner.
rewrite:
    Python: symmath.py. SymPy's rewrite in terms of the target function.
partfrac, numden, coeffs:
    Python: symmath.py. sympy.apart; sympy.fraction of sympy.together; the terms of sympy.Poly in the variables, sorted by power.
children, has, lhs, rhs, isolate, finverse:
    Python: symmath.py. The expression's args; SymPy's has; an equation's two sides; sympy.solve for the variable (finverse solves y = f(x) for x and calls y x).
subs:
    Python: symmath.py. SymPy's subs with simultaneous=True, for each element, or for each value of an array of values; subs(e) looks the expression's variable names up in the caller's workspace.
solve:
    Python: symmath.py. sympy.solve with dict=True on the equations as expression == 0 (cubics solved by radicals, quartics only with 'MaxDegree' 4), solutions kept when they agree with the variables' assumptions and the inequalities assumed; 'Real' solves for real symbols. 'ReturnConditions' uses sympy.solveset: a family k*pi + c (an ImageSet) becomes a solution in k with the condition in(k, 'integer'). Inequalities go to sympy.solve as they are. solve of an ode object: odemore.py, the solver its Solver selects. solve of an optimization or equation problem: optimprob.py (see optimproblem).
vpasolve:
    Python: symmath.py. A polynomial in one variable: all its roots by SymPy's nroots to digits places; otherwise sympy.nsolve (mpmath's findroot) from the start given (0, or the middle of a range; bisection within a range), trying other starts when the first fails.
dsolve:
    Python: symmath.py. sympy.dsolve on the equations with the unknown functions they hold; conditions y(a) == b and Dy(a) == b go to it as ics. The answers are the right sides.
laplace, ilaplace:
    Python: symmath.py. sympy.laplace_transform with noconds=True, the time variable taken positive; sympy.inverse_laplace_transform into a positive t, so that no heaviside(t) is left.
fourier, ifourier:
    Python: symmath.py. sympy.fourier_transform, which uses exp(-2*pi*1i*k*x), at k = w/(2*pi); the integral itself (sympy.integrate) when it gives none. The inverse likewise from sympy.inverse_fourier_transform.
ztrans, iztrans:
    Python: symmath.py. The sum of f(n)*z^(-n) by sympy.summation (its first case when it is piecewise). The inverse of a rational F: for n >= 1 the sum of the residues of F(z)*z^(n-1) at the roots of the denominator (sympy.roots), each as the (m-1)-th derivative of (z-p)^m*F(z)*z^(n-1) at p over (m-1)!, and at n = 0 the limit of F at infinity (a kroneckerDelta term when they differ).
assume, assumeAlso, assumptions:
    Python: symmath.py. A new sympy.Symbol of the name with SymPy's assumptions (real, positive, negative, nonnegative, integer, rational, nonzero); an inequality with another bound is kept beside it and used to filter solve's solutions.
isAlways:
    Python: symmath.py and symbolic.py. sympy.simplify of the condition, and for an equation of the difference of its sides, to SymPy's true or false; otherwise unknown.
latex, pretty:
    Python: symmath.py. sympy.latex, and sympy.pretty with Unicode.
matlabFunction:
    Python: symmath.py. The expression printed in the language's syntax (symbolic.py's printer) with element-wise operators, made into an anonymous function of the variables as str2func makes one; with 'File' written into a function file of the current folder.
fimplicit:
    Python: symmath.py. f on a 201-by-201 grid of the range ([-5 5] unless given) and its zero contour drawn by contour.
fplot3:
    Python: symmath.py. x(t), y(t) and z(t) at 400 points of the range ([-5 5] unless given), drawn by plot3.
heaviside, dirac, sinc, lambertw, zeta, kroneckerDelta:
    Python: symmath.py. For numbers: NumPy for heaviside (1/2 at 0), dirac (Inf at 0), sinc and kroneckerDelta; scipy.special.lambertw and scipy.special.zeta. For symbolic values SymPy's Heaviside, DiracDelta, LambertW, zeta and KroneckerDelta.

# ---- funfun.py: functions of functions --------------------------------------------------------
optimset:
    Python: funfun.py. A struct of options: Display, MaxFunEvals, MaxIter, TolFun, TolX, FunValCheck, OutputFcn and PlotFcns start empty, a struct given first is taken over, and each name-value pair sets one, the name matched without regard to case. The solvers read these older names too.
optimoptions, resetoptions:
    Python: optim.py. An options object for one solver: the names it knows with their defaults, the ones set kept apart (so the display can list them), the older optimset names (TolFun, TolX, MaxIter, ...) read as the newer ones. A value object: changing a copy leaves the original as it was. Options of another solver are carried over where they apply.
fminunc:
    Python: optim.py. 'quasi-newton': scipy.optimize.minimize with method 'BFGS', gtol OptimalityTolerance and xrtol StepTolerance; 'trust-region': method 'trust-constr' with the Hessian from HessianFcn 'objective' or a BFGS update. Gradients not given are forward differences (central with FiniteDifferenceType 'central') with steps sqrt(eps)*max(abs(x), TypicalX), counted in funcCount; the answer is judged by central differences. The sixth output is the Hessian by differences of the gradient at x. Each iterate goes through SciPy's callback to the Display row and the output and plot functions.
fmincon:
    Python: optim.py. 'interior-point' and 'trust-region-reflective': scipy.optimize.minimize with method 'trust-constr' (an interior point method for the inequalities) with a BFGS Hessian, then SLSQP started from its answer so that x lands on the active constraints; 'sqp', 'sqp-legacy' and 'active-set': SLSQP alone (sequential least squares programming). Linear constraints go to SciPy as LinearConstraint, c and ceq as NonlinearConstraint, with their Jacobians by forward differences unless given. The Lagrange multipliers are the nonnegative least-squares solution of grad f + J'*lambda = 0 over the constraints active at x (scipy.optimize.lsq_linear), and the first-order optimality the largest part of what is left.
fsolve:
    Python: optim.py. 'trust-region-dogleg' on a square system: scipy.optimize.root with method 'hybr', MINPACK's modification of Powell's hybrid method; otherwise, and for systems with more equations than unknowns, scipy.optimize.least_squares ('lm' for 'levenberg-marquardt', else its trust-region reflective method). Solved when sum(F.^2) is below FunctionTolerance squared.
lsqcurvefit, lsqnonlin:
    Python: optim.py. scipy.optimize.least_squares on the residuals fun(x, xdata) - ydata, or fun(x): the trust-region reflective method with the bounds, 'lm' for 'levenberg-marquardt' without them; ftol, xtol and gtol a hundredth of FunctionTolerance, StepTolerance and OptimalityTolerance. With linear or nonlinear constraints the sum of squares is minimized as fmincon minimizes. resnorm is the sum of the squared residuals; the Jacobian is the seventh output.
lsqlin:
    Python: optim.py. With bounds alone, scipy.optimize.lsq_linear (bounded-variable least squares); with linear constraints, quadprog's method on H = C'*C and f = -C'*d.
lsqnonneg:
    Python: optim.py. scipy.optimize.nnls, the Lawson-Hanson active-set method for the least-squares x >= 0. lambda is the dual vector C'*(d - C*x), zero where x is positive.
quadprog:
    Python: optim.py. With equalities alone, the KKT system [H Aeq'; Aeq 0] solved directly. Otherwise scipy.optimize.minimize with method 'trust-constr' (an interior point method) and the exact Hessian H; then the constraints active at its answer (within 1e-6, 1e-4 or 1e-3 of their limits) are held as equalities and the KKT system solved exactly, the result kept when it is feasible, no worse and its multipliers have the right signs. H's smallest eigenvalue (numpy.linalg.eigvalsh) says whether the problem is convex.
linprog:
    Python: optim.py. scipy.optimize.linprog with HiGHS: method 'highs-ds' (dual simplex) for 'dual-simplex', 'highs-ipm' for the interior point algorithms; ConstraintTolerance and OptimalityTolerance as HiGHS' primal and dual feasibility tolerances. The multipliers are HiGHS' marginals (the change of the objective per unit of each right side) with the sign that makes them nonnegative.
intlinprog:
    Python: optim.py. scipy.optimize.milp, HiGHS' branch and bound, with the integrality of the variables in intcon, time_limit MaxTime, mip_rel_gap RelativeGapTolerance and node_limit MaxNodes; the integer variables of the answer are rounded to whole numbers.
fminimax:
    Python: optim.py. SLSQP on the variables and one more, t: minimize t with fun(x) <= t (and -fun(x) <= t for the first AbsoluteMaxObjectiveCount), the problem's own constraints kept.
fgoalattain:
    Python: optim.py. SLSQP on the variables and the attainment factor gamma: minimize gamma with fun(x) - weight*gamma <= goal (both ways for the first EqualityGoalCount), the problem's own constraints kept.
optimplotfval, optimplotx, optimplotfirstorderopt, optimplotfunccount, optimplotconstrviolation, optimplotstepsize, optimplotresnorm:
    Python: optim.py. At 'init' the solver opens a window with one axes for each plot function; at each call the function adds the iteration's point to its line (a new line at 'init'; optimplotx redraws its bars) and puts the value in the title. The window is drawn when the solver is done, not while it runs.
optimget, odeget:
    Python: funfun.py. The option's value from the struct, the name matched without regard to case, or the default given when it is empty or missing.
odeplot:
    Python: funfun.py. An output function: at 'init' it makes one line for each solution component in the current axes (newplot), with the x-limits set to the time span; at each step it appends the step's times and values to the lines' XData and YData; at 'done' it forgets them.
fzero:
    Python: funfun.py. With an interval [a b] whose ends differ in sign, scipy.optimize.brentq (Brent's method: bisection, secant and inverse quadratic steps) with xtol TolX (eps unless given) and rtol 4*eps. From one point x, a sign change is looked for first: steps of abs(x)/50 (1/50 at 0), growing by sqrt(2) each time, are tried to the left and then the right, up to 200 times. A complex or non-finite value of the function stops it.
fminbnd:
    Python: funfun.py. scipy.optimize.minimize_scalar with method 'bounded': Brent's method of golden-section search and parabolic interpolation, within [a b], with xatol TolX (1e-4 unless given).
fminsearch:
    Python: funfun.py. scipy.optimize.minimize with method 'Nelder-Mead'. The first simplex has the start point and, for each component, the point with that component 5% larger (0.00025 where it is 0); xatol and fatol are TolX and TolFun (1e-4 unless given), and MaxIter and MaxFunEvals default to 200 times the number of unknowns.
integral:
    Python: funfun.py. scipy.integrate.quad, QUADPACK's adaptive Gauss-Kronrod quadrature (21 points on a finite interval; an infinite one is mapped onto a finite one), with RelTol 1e-6 and AbsTol 1e-10 unless given, at most 650 subintervals, and real Waypoints as break points. Complex limits or waypoints make a path: each straight segment z0 + t*(z1 - z0), t from 0 to 1, with the integrand times z1 - z0. Complex values are integrated as their real and imaginary parts. The function is called one point at a time; 'ArrayValued' uses scipy.integrate.quad_vec.
quad, quadl, quadgk:
    Python: funfun.py. scipy.integrate.quad (QUADPACK's adaptive Gauss-Kronrod rule), complex values as their real and imaginary parts. quad and quadl take the tolerance (1e-6 unless given) and pass the parameters after trace to the function; their second output is the number of evaluations. quadgk takes RelTol, AbsTol, Waypoints (a path when complex) and ArrayValued (scipy.integrate.quad_vec), and its second output is the error estimate.
integral2, quad2d, dblquad:
    Python: funfun.py. scipy.integrate.dblquad, QUADPACK's quadrature in y inside quadrature in x, with the y limits numbers or functions of x; AbsTol 1e-10 and RelTol 1e-6.
integral3, triplequad:
    Python: funfun.py. scipy.integrate.tplquad: three nested QUADPACK quadratures over the limits given, with SciPy's default tolerances.
interp1:
    Python: funfun.py. The points x are sorted first (repeated x is refused) and each column of V interpolated. 'linear' (the default) is numpy.interp, NaN outside x unless 'extrap' (scipy.interpolate.interp1d then extends the end pieces) or an extrapolation value. 'nearest', 'next' and 'previous' are scipy.interpolate.interp1d of that kind; 'pchip' and 'cubic' are scipy.interpolate.PchipInterpolator; 'makima' is scipy.interpolate.Akima1DInterpolator with method 'makima'; 'spline' is scipy.interpolate.CubicSpline with not-a-knot ends (natural ends for three points). These last four extrapolate unless a value is given.
interp2, interpn:
    Python: funfun.py. Along each dimension a matrix of weights takes the values at the grid points to the query points: 'linear', 'nearest' (a half rounds up), 'spline' (scipy.interpolate.CubicSpline of the identity, not-a-knot) and 'cubic' (Keys' cubic convolution with a = -1/2 on an even grid, its ends extended by f(-1) = 3f(0) - 3f(1) + f(2); the spline otherwise). The weights are applied one dimension after the other, to a grid of query vectors or to query points; a NaN value spreads only where its weight is not zero. 'pchip' and 'makima' are not linear in the values: on a grid scipy.interpolate.PchipInterpolator or Akima1DInterpolator one dimension at a time, at points scipy.interpolate.RegularGridInterpolator. Complex values are interpolated as real and imaginary parts. Grids that decrease are turned around; outside the grid the values are NaN or the extrapolation value.
griddata:
    Python: funfun.py. scipy.interpolate.griddata on scattered points, by a Delaunay triangulation: linear in each triangle, nearest, or cubic (Clough-Tocher); 'natural' is taken as linear and 'v4' as cubic.
spline:
    Python: funfun.py. scipy.interpolate.CubicSpline with not-a-knot ends (natural ends for two points), along the last dimension of the values (each row of a matrix is a curve); with two more values than points, the first and last are the end slopes (clamped ends). The points are sorted first, and points of a vector whose value is NaN are left out. With two inputs it returns the piecewise polynomial, its coefficients taken from SciPy's.
pchip:
    Python: funfun.py. scipy.interpolate.PchipInterpolator along the last dimension of the values (points sorted first): piecewise cubic Hermite interpolation with slopes chosen to keep the data's monotonicity (Fritsch and Carlson); with two inputs, the piecewise polynomial.
makima:
    Python: funfun.py. scipy.interpolate.Akima1DInterpolator with method 'makima', extrapolating at the ends.
ppval:
    Python: funfun.py. Each point's piece is found by numpy.searchsorted on the breaks (the end pieces extend outside them) and the polynomial of each value component evaluated by Horner's rule in x - breaks(k); the points are taken in column order, and a value of size d gives an array of size [d, size(xx)] ([d, length(xx)] for a vector xx).
mkpp, unmkpp:
    Python: funfun.py. A piecewise polynomial object holding the breaks, the coefficients (a row for each piece and value component, the components of a piece together, highest power first; a vector of them is reshaped in column order) and the size of a value, and back.
polyfit:
    Python: funfun.py. The Vandermonde matrix of x (numpy.vander), factored by numpy.linalg.qr, and the coefficients from R p = Q'y (scipy.linalg.solve_triangular); when the matrix's rank is below the degree plus one, numpy.linalg.lstsq and a warning. S holds R, the degrees of freedom, the norm of the residuals and R^2. With three outputs, x is first centred and scaled by its mean and standard deviation, returned as mu.
polyval:
    Python: funfun.py. Horner's rule, element by element by NumPy (y = y.*x + c for each coefficient); with mu, x is first centred and scaled. The second output from polyfit's S: normr/sqrt(df)*sqrt(1 + sum((A/R).^2, 2)) with A the Vandermonde rows of x (scipy.linalg.solve_triangular for A/R), Inf when df is 0. single in gives single out.
polyvalm:
    Python: funfun.py. Horner's rule with matrix products: Y = Y*X + c*I for each coefficient.
roots:
    Python: funfun.py. The eigenvalues (numpy.linalg.eigvals) of the companion matrix of the polynomial, after leading zeros are taken off; trailing zeros give roots at 0.
poly:
    Python: funfun.py. The roots (or a square matrix's eigenvalues, by numpy.linalg.eigvals) multiplied out by repeated convolution with [1 -r] (numpy.convolve); real when the roots come in conjugate pairs.
conv:
    Python: funfun.py. numpy.convolve; 'same' and 'valid' take the central part and the part computed without the zero padding.
deconv:
    Python: funfun.py. scipy.signal.deconvolve: the polynomial division of b by a, quotient and remainder.
polyder:
    Python: funfun.py. numpy.polyder; polyder(a, b) with one output is the derivative of their product numpy.convolve(a, b).
polyint:
    Python: funfun.py. The coefficients divided by n, n - 1, ..., 1, with the constant k (0 unless given) appended.
residue:
    Python: funfun.py. scipy.signal.residue: the partial fraction expansion of b/a, residues, poles and the direct term, a repeated pole's residues in increasing powers, the groups of equal poles (within 1e-3) put in order of decreasing magnitude. With three inputs, scipy.signal.invres puts r, p and k back together into b and a.
filter:
    Python: funfun.py. scipy.signal.lfilter, the direct form II transposed structure, along the first dimension whose size is not 1 or the one given, with the initial conditions zi and the final ones returned.
filter2:
    Python: funfun.py. scipy.signal.correlate2d, the kernel slid over the data without being rotated, 'same' size unless asked otherwise.
conv2:
    Python: funfun.py. scipy.signal.convolve gives the full convolution, and 'same' keeps its part from floor(size(B)/2) the size of A, 'valid' its part from size(B) the size of A less that of B plus 1 (empty when B is larger); conv2(u, v, A) convolves A down its columns with u and along its rows with v. convn does the same in any number of dimensions. single stays single.
convn:
    Python: funfun.py. scipy.signal.convolve with method 'direct'.
fft, ifft:
    Python: funfun.py. numpy.fft.fft and numpy.fft.ifft along the first dimension whose size is not 1 or the one given, the data cut or padded with zeros to n; 'symmetric' keeps the real part of ifft.
fft2, ifft2, fftn, ifftn:
    Python: funfun.py. numpy.fft.fft2, numpy.fft.ifft2, numpy.fft.fftn and numpy.fft.ifftn.
fftshift, ifftshift:
    Python: funfun.py. numpy.fft.fftshift and numpy.fft.ifftshift, over every dimension or the one given.
detrend:
    Python: funfun.py. scipy.signal.detrend along the first dimension whose size is not 1: the least-squares line taken off ('linear', the default), or the mean (0 or 'constant').
gradient:
    Python: funfun.py. Along each dimension (x the second, y the first, then the rest): one-sided differences at the ends and (f(i+1) - f(i-1))/(x(i+1) - x(i-1)) inside, with a scalar spacing or the coordinates given.
del2:
    Python: funfun.py. Along each dimension the second differences 2*((f(i+1) - f(i))/h(i) - (f(i) - f(i-1))/h(i-1))/(h(i-1) + h(i)) inside, extended linearly to the ends (constantly when there is one inner point), added and divided by 2N (by 4 for a vector).
# ---- sparse.py and sparsemat.py: sparse matrices --------------------------------------------------
sparse:
    Python: sparse.py and sparsemat.py. A sparse matrix is a SciPy matrix in compressed sparse column form (scipy.sparse.csc_matrix): for each column, the row indices of its nonzeros, in order, and their values, double (real or complex) or logical. Explicit zeros are removed after every operation. sparse(i, j, v, m, n) builds the matrix from the triplets with scipy.sparse.coo_matrix, which adds the values given for one place (logical values are combined by or); sparse(A) keeps A's nonzeros; sparse(m, n) has none.

    The operators in sparsemat.py work on SciPy's matrices where the result is sparse: S + S, S - S and S .* S element by element on the stored values; S .* A and S ./ c, S .^ c (c > 0) and comparisons with a scalar that are false at zero, on the stored values alone; S * S by SciPy's sparse product; S \ S and S \ b with a square S by SuperLU (scipy.sparse.linalg.splu), with the singular-matrix warning and a full solve when it fails; a rectangular S by least squares on the full matrix, or when that is too large to make, by SuperLU on the augmented system [c*I S; S' 0] (c is max(max(abs(S)))/1000). Any other operator works on the full arrays and keeps the result sparse as the language does: + and - with a full operand or a scalar give full results, .* and & give sparse ones, ./ and .^ are sparse when the left operand is. Indexing slices SciPy's matrix; assignment goes through scipy.sparse.lil_matrix and back.

    Functions that keep a zero zero (abs, sqrt, sin, round, isnan and so on) work on the stored values alone; others (cos, exp) compute on the full matrix and store the result sparse. sum, any, all, max, min, find, reshape, diag, tril, triu, kron, repmat, blkdiag, trace and isequal use SciPy's methods without making the matrix full; the rest of the functions that keep sparse results (cumsum, diff, flip, mean, chol, qr, ...) compute on the full matrix and store their first result sparse. zeros, ones, eye, true and false with 'like' and a sparse value make the full array and store it sparse. A function written for full arrays reads a sparse matrix as a full one, refusing one of more than 2^25 elements.
full:
    Python: sparse.py. SciPy's toarray, in column order.
issparse:
    Python: sparse.py. True for the sparse type (values.Sparse), whatever its values.
speye, spzeros, spalloc:
    Python: sparse.py. scipy.sparse.eye of the size asked for, or a matrix with no nonzeros; spalloc reserves no room, as SciPy makes room as a matrix is filled.
spones:
    Python: sparse.py. The matrix's pattern with every stored value set to 1.
sprand, sprandn:
    Python: sparse.py. round(density*m*n) distinct places drawn by numpy.random.RandomState.choice from rand's generator (for more than 2^24 elements, random integers with repeats dropped), with uniform values in (0, 1) or normal ones; sprand(S) and sprandn(S) put new values on S's pattern.
sprandsym:
    Python: sparse.py. Places drawn as for sprandn, the ones on and below the diagonal kept, normal values put there and the strict lower triangle mirrored above (scipy.sparse.tril); sprandsym(S) uses the lower triangle of S's pattern.
spdiags:
    Python: sparse.py. The diagonals of A (scipy.sparse.csc_matrix.diagonal) as the columns of B, each aligned by the column of A when m >= n and by the row otherwise; or B's columns put on the diagonals d of an m-by-n matrix (or of A) through scipy.sparse.lil_matrix.
nzmax:
    Python: sparse.py. The number of stored nonzeros, at least 1, as SciPy keeps no room beyond them; numel for a full array.
nonzeros:
    Python: sparse.py. The stored values in column order (SciPy's COO form sorted by column, then row) as a full column; for a full array, the elements that are not zero, down the columns.
spconvert:
    Python: sparse.py. The rows [i j v] (or [i j re im]) as triplets to scipy.sparse.coo_matrix, the size from the largest i and j (a last row [m n 0] sets it).
normest:
    Python: sparse.py. The power method on S'*S from the column sums of abs(S): x = S'*(S*x), the estimate norm(x)/norm(S*x), until two estimates differ by less than tol (1e-6) times the latest; a warning after 100 iterations.
symrcm:
    Python: sparse.py. scipy.sparse.csgraph.reverse_cuthill_mckee on the pattern of S + S'.
amd, symamd:
    Python: sparse.py. Minimum degree on the pattern of S + S': the node with fewest neighbours (the lowest index first among equals) is eliminated, its neighbours joined to each other, and so on until none is left. The degrees are exact, not the approximate ones of AMD, so the order can differ from AMD's while reducing fill in the same way.
colamd:
    Python: sparse.py. The minimum degree ordering of amd on the pattern of S'*S.
etree:
    Python: sparse.py. Liu's algorithm with path compression over the upper triangle, column by column: each row index above the diagonal is followed up its ancestors to their root, which gets column j as its parent. The postorder q is a depth-first walk of the tree, children in increasing order.
dmperm:
    Python: sparse.py. scipy.sparse.csgraph.maximum_bipartite_matching (Hopcroft and Karp) of the columns to the rows of the pattern.
sprank:
    Python: sparse.py. The number of columns matched by scipy.sparse.csgraph.maximum_bipartite_matching.
ichol:
    Python: sparse.py. Column by column in Python (left-looking): column k of the lower triangle less L(k:n, j)*L(k, j)' for each earlier column j with an entry in row k; for 'nofill' only the places in A's pattern are updated (with michol the update of a place outside it goes to the two diagonals instead), for 'ict' entries below droptol*norm(A(k:n, k), 1) are dropped (with michol added to both diagonals). The pivot's square root is L(k, k) and the column is divided by it; on the diagonal |L(k, j)|^2 is taken as a real number, so a Hermitian matrix keeps real pivots. diagcomp adds alpha*diag(diag(A)) first; 'upper' factors the conjugate transpose of the upper triangle and returns L'.
ilu:
    Python: sparse.py. Column by column in Python (left-looking): column j of A is solved against the columns of L so far, taking them in order of their steps (a heap); an entry of U smaller than droptol*norm(A(:, j)) is dropped before it is used, as is an entry of the new column of L (before the division by the pivot); for 'nofill' the updates outside A's pattern are left out. 'crout' and 'nofill' take row j as the pivot; 'ilutp' takes the largest of the rows not yet used unless row j is at least thresh times it. milu 'col' adds what the column dropped to its pivot, keeping the column sums of L*U; 'row' runs the column version on A.' and turns its factors back (L = U2.'*inv(D), U = D*L2.' with D U2's diagonal), keeping the row sums. A zero pivot is an error unless udiag is set.
spaugment:
    Python: sparse.py. scipy.sparse.bmat of [c*I A; A' 0], c max(max(abs(A)))/1000 unless given.
spparms:
    Python: sparse.py. A list of the settings with their usual values, kept in the engine and read back; SciPy's SuperLU and ARPACK are called with their own settings, so none of them changes a result.
spy:
    Python: sparse.py. plot of the column against the row of each nonzero (SciPy's COO form), marker '.', with axis ij, the limits 0 to n+1 and 0 to m+1, and the count nz under the axes.

# ---- timefun.py: dates and times as numbers -----------------------------------------------------
clock, now, date:
    Python: timefun.py. Python's datetime.now (the browser's local time): as [year month day hour minute seconds], as a date number, or as 'dd-mmm-yyyy'.
datenum:
    Python: timefun.py. Days from 1 January of year 0 (day 1) in the proleptic Gregorian calendar, worked out from the year, month and day with Howard Hinnant's days-from-civil formulas in whole numbers (so year 0 and the years before it work), and the time of day as the fraction; months past 12 or below 1 roll into the years, a fraction of a year or month adds that part of its days, and days, hours, minutes and seconds may run past their ranges. Text is read with regular expressions built from the date format's tokens (yyyy, yy, mmmm, mmm, mm, dd, HH, MM, SS, FFF, AM/PM), either the format given or a list of standard ones tried in turn; two-digit years fall in the hundred years from 50 years ago, a missing year is this year and a missing month and day are 1 January.
datevec:
    Python: timefun.py. The whole days turned back into year, month and day with the civil-from-days formulas, the fraction into hours, minutes and seconds; the seconds rounded to what the date number can hold (about 1e-5 s for dates of today), carrying into the next day when they round up. Text is read as datenum reads it, the seconds kept as written. With several outputs each has the shape of the input.
datestr:
    Python: timefun.py. A formatter of its own for the date format's tokens (yyyy, yy, mmmm, mmm, mm, m, dddd, ddd, dd, d, HH, MM, SS, FFF, AM/PM and QQ) and the numbered formats 0 to 31, the day of the week from the days since 1970-01-01 (a Thursday); the date vector is first rounded to whole milliseconds, carrying in whole numbers. Without a format, 'dd-mmm-yyyy HH:MM:SS', or 'dd-mmm-yyyy' when every time is midnight.
weekday:
    Python: timefun.py. mod(floor(d) - 2, 7) + 1, so 1 is Sunday, in the shape of d, and the day's short name (or long name with 'long'); text is read as datenum reads it.
eomday, leapyear:
    Python: timefun.py. The days of each month from a table, plus one for February of a leap year; a leap year is divisible by 4, and not by 100 unless by 400 (the proleptic Gregorian calendar, year 0 and before included).
etime:
    Python: timefun.py. The whole days between the two dates (their dates as date numbers) times 86400, plus the difference of the hours, minutes and seconds: no rounding through date numbers, so the seconds come out as exact as the vectors are.
addtodate:
    Python: timefun.py. Days, weeks, hours, minutes, seconds and milliseconds are added to the date number as fractions of a day; months and years (whole numbers) are added to the date vector, a day past the end of the new month becoming its last day, and turned back into a number.

# ---- timetypes.py and vobj.py: datetime, duration, calendarDuration ----------------------------------
datetime:
    Python: timetypes.py and vobj.py. A datetime holds a float64 array of seconds since 1970-01-01 00:00:00: the wall clock when it has no time zone, UTC when it has one, its TimeZone giving the wall clock for display and the calendar (Python's zoneinfo; in the page, where Python has no zone database, the browser's own through Intl.DateTimeFormat, the wall clock it gives for each instant minus the instant; or a fixed offset such as '+01:00'). NaT is NaN. Year, month and day come from the days by Howard Hinnant's civil calendar (the proleptic Gregorian, as datenum's), and back the same way, months past 12 and days past the month's end carried. Text is read by a regular expression built from the format's letters, or by the first of a list of usual formats (ISO 8601 first) that reads every element; the display format is built from the same letters. Datetimes are value objects: indexing, assignment, deletion and concatenation make new ones, and the operators come to the class (comparisons, minus between datetimes giving a duration, plus or minus a duration, a calendarDuration or a number of days).
NaT, isdatetime, isnat:
    Python: timetypes.py. NaT is a datetime of NaN; isnat is numpy.isnan of the seconds.
year, month, day, hour, minute, second, quarter, ymd, hms, timeofday:
    Python: timetypes.py. The parts of the wall-clock seconds: the day by floor division by 86400 and the civil calendar, the time of day split into hours, minutes and seconds; the day of the week from 1970-01-01, a Thursday; names from English month and day names.
week:
    Python: timetypes.py. Weeks start on Sunday; the week of 1 January (or of the month's first day) is 1, counted from the weekday of that day.
isweekend, isbetween:
    Python: timetypes.py. The weekday is 0 or 6 (Sunday or Saturday); isbetween compares the seconds, its ends included unless 'open', 'openleft' or 'openright'.
posixtime, juliandate, exceltime, convertTo:
    Python: timetypes.py. From the seconds: posix time is them (UTC for a zoned datetime), the Julian date seconds/86400 + 2440587.5 (minus 2400000.5 for the modified one), Excel's day number the date number less 693960 (695422 for 1904 dates), yyyymmdd from the year, month and day.
tzoffset:
    Python: timetypes.py. The zone's offset from UTC at each instant (zoneinfo's utcoffset), as a duration; 0 for a datetime with no zone.
dateshift:
    Python: timetypes.py. The start of the unit holding each datetime (the first day of the year, quarter or month, the Sunday of the week, the whole day, hour, minute or second), moved by the rule's number of units (months by the calendar); 'end' is the start of the next unit. 'dayofweek' moves to the next (or previous, or nearest) day with that weekday, the time of day kept.
between, caldiff:
    Python: timetypes.py. Whole months first (the largest number that, added to the first datetime by the calendar, does not pass the second), then whole days, then the time left, as far as the components asked for; a later first datetime gives the negative.
duration:
    Python: timetypes.py. A float64 array of seconds. Displayed as hh:mm:ss (hours past 24 kept in the hours), dd:hh:mm:ss, hh:mm or mm:ss, the seconds truncated (or with as many fraction digits as S letters), or as a number of one unit with five significant digits. Text is read as [dd:]hh:mm:ss, hh:mm or a number with its unit.
isduration:
    Python: timetypes.py. True for the duration class.
years, days, hours, minutes, seconds, milliseconds:
    Python: timetypes.py. A number times the unit's seconds (a year of 365.2425 days), as a duration displayed in that unit; given a duration, its seconds divided by the unit's.
calendarDuration:
    Python: timetypes.py. Three float64 arrays: months, days and seconds. Added to a datetime, the months move the wall-clock date by the calendar (the day kept, or the last day of a shorter month), then the days, then the seconds. Displayed as years, months and days (1y 2mo 3d) and the time in hours, minutes and seconds.
iscalendarduration:
    Python: timetypes.py. True for the calendarDuration class.
calyears, calquarters, calmonths, calweeks, caldays:
    Python: timetypes.py. Whole numbers of 12, 3 or 1 months, or 7 or 1 days; given a calendarDuration, its months (or days) in that unit.

# ---- categoricals.py and tables.py: categorical arrays, tables and timetables ---------------------
categorical:
    Python: categoricals.py and vobj.py. A float64 array of codes (1 for the first category, 0 for undefined) beside the list of category names, ordinal and protected. The categories are the distinct values sorted (numbers by value, text by the characters' codes), or valueset in its order; each element's code comes from a Python dictionary of the names. Assignment, concatenation and comparison turn text into codes, adding categories where the array is not protected; < and > compare codes and need ordinal.
categories, iscategorical, isordinal, isprotected, isundefined, iscategory:
    Python: categoricals.py. The names as a column cell array; the class, the two flags, codes of 0, and Python's in on the names.
countcats:
    Python: categoricals.py. For each category, the elements whose code is its number, summed along the dimension; the undefined (code 0) are not counted.
addcats, removecats, mergecats, renamecats, reordercats, setcats:
    Python: categoricals.py. A new list of names and the codes mapped to it through a table of old code to new code (0 where a category is gone).
summary:
    Python: categoricals.py and tables.py. For a categorical array, countcats beside the names. For a table, each variable in turn: numbers by numpy.min, numpy.median and numpy.max over the values that are not NaN, and the count of NaN; datetimes and durations the same on their seconds; categories and logical values counted.
table:
    Python: tables.py and vobj.py. A list of variables (any values of the same number of rows), a list of names, the row names (or None) and the properties. A table is a value object: indexing picks rows (numbers, a mask, names looked up in the row names) and variables (numbers, a mask, names, vartype), and builds a new table from each variable's rows; assignment, deletion and concatenation build new tables the same way, filling new rows with a missing value of each variable's class (NaN, empty text, <missing>, NaT, undefined). Each variable's values are marked shared, so a change through T.x(2) = v copies the variable first. The compiler passes the names of the variables given to table, so that they name its variables. The display puts each variable's values in a block, numbers to the right and text to the left, centred under its name, fractions with five significant digits. table(results): unittests.py, a column for each property of the results.
timetable:
    Python: tables.py. A table whose row names are a datetime or duration column, the row times; rows are picked by times (compared by their seconds) or by a timerange. SampleRate and TimeStep give the row times start + (0:n-1)*step. TimeStep and SampleRate in the properties come from the differences of the row times when they are all equal.
istable, istimetable, istabular:
    Python: tables.py. The class.
height, width:
    Python: tables.py. The size along the first and second dimensions.
head, tail:
    Python: tables.py. The first or last k rows (8), by indexing.
vartype, timerange:
    Python: tables.py. Small objects that table indexing asks which variables (by class) or rows (by comparing the row times' seconds with the two ends) they pick.
table2array, table2cell, table2struct, struct2table, cell2table, array2table:
    Python: tables.py. The variables concatenated side by side (as [T.a, T.b] would be), split row by row into cells or struct elements, or built from the columns of a cell or numeric array (a cell column of numbers becomes a numeric variable, any other column stays a cell).
table2timetable, timetable2table:
    Python: tables.py. A datetime or duration variable moved into the row times, or the row times moved into the first variable.
addvars, removevars, movevars, renamevars, splitvars, mergevars, rows2vars, convertvars:
    Python: tables.py. New lists of variables and names; splitvars indexes each column out, mergevars concatenates the variables side by side, rows2vars makes a variable of each row (numbers when every value of the row is a number, else a cell), and convertvars calls the conversion function by name (or the function handle) on each variable.
varfun, rowfun:
    Python: tables.py. The function called on each variable (varfun) or on the values of each row (rowfun), or on each group's rows; the groups are the distinct rows of the grouping variables, sorted, found through a Python dictionary.
groupsummary:
    Python: tables.py. The groups as for varfun; each method on each group's values that are not NaN: numpy.nanmean, numpy.nansum, numpy.nanmin, numpy.nanmax, numpy.nanmedian, numpy.nanvar and numpy.nanstd with one degree of freedom less, the most frequent value by numpy.unique, or the function given.
innerjoin, outerjoin:
    Python: tables.py. Each row's keys as a tuple; a Python dictionary from B's keys to its rows gives the pairs of matching rows, then the rows of either table with no match (outerjoin), sorted by the keys; each variable is indexed by the pairs, a missing value where a row has none.
retime, synchronize:
    Python: tables.py. The row times sorted, and the new times built from the first to the last (calendar units from dateshift's start of the unit, or a fixed step); 'previous', 'next' and 'nearest' pick rows by numpy.searchsorted on the seconds; 'linear', 'spline', 'pchip' and 'makima' are scipy.interpolate.interp1d, scipy.interpolate.CubicSpline, scipy.interpolate.PchipInterpolator and scipy.interpolate.Akima1DInterpolator over the values that are not NaN, extrapolating; the methods that put rows together take the rows from each new time up to the next. synchronize retimes each timetable to the union (or the other basis) of the row times and puts them side by side.
isregular:
    Python: tables.py. numpy.diff of the row times' seconds, all equal; for a calendar unit, whether each time is the first plus a whole number of the unit times its position.
readtable:
    Python: tables.py. Text files read by Python's csv module (the delimiter the most common of comma, tab, semicolon and bar in the first lines, unless given), spreadsheets by reading the .xlsx file's XML with Python's zipfile and xml.etree. A column is numbers when every filled cell reads as one (NaN for the empty ones), datetimes when every filled cell reads as one of the usual date formats, else text. Names are made valid by matlab.lang.makeValidName.
writetable:
    Python: tables.py. Rows of text written with the delimiter, text with the delimiter or quotes in it quoted; a variable of several columns becomes Name_1, Name_2, ...; datetimes and categories as they display. An .xlsx file is written as the few XML parts of a workbook of one sheet, text in its shared strings.

# ---- parallel.py: the pool for parfor ---------------------------------------------------------
parpool, gcp:
    Python: parallel.py. The workers are Python engines of their own: in the page, Web Workers beside the one that runs the Command Window, each with Pyodide and the engine. The default pool has one worker for each processor core but one (at most 8). For a parfor loop each worker gets the loop's compiled code, its broadcast and sliced values and the files that changed, then blocks of passes as the workers come free; the slices and the reductions' parts come back and are put together in the order of the passes, so the result is the one a serial run gives. gcp starts the default pool unless 'nocreate' is given; delete(gcp) stops it.
getCurrentTask:
    Python: parallel.py. A struct with the worker's ID while a parfor pass runs on a worker; [] otherwise.
# ---- core.py: the language's own functions ----------------------------------------------------
disp:
    Python: core.py and display.py. The text the Command Window shows for the value, without its name: numbers laid out by the current format, text as its rows, a struct's fields, a cell's contents; an empty value prints nothing.
display:
    Python: core.py and display.py. What the Command Window shows for a result left without a semicolon: the name, an equals sign and the value laid out by the current format.
format:
    Python: core.py and display.py. Sets how numbers are shown, never the numbers themselves. 'short' gives 4 decimals and 'long' 15 (a scalar outside [0.001, 1000) in e notation, a matrix with a common power of ten taken out); 'shortE' and 'longE' are Python's %e, 'shortG' and 'longG' %g with 5 or 15 digits, 'bank' 2 decimals, 'rat' a continued fraction and 'hex' the IEEE bytes. Whole numbers are shown without decimals, and 'compact' leaves out the blank lines.
sprintf, fprintf:
    Python: core.py and fmt.py. The format's conversions are found by a regular expression and each is written by Python's % operator with the same flags, width and precision; escapes such as \n become characters first. The format is used again from its start while arguments are left, the arguments' elements taken down the columns. A point with no number after it (%.f) means no decimals. %s takes a whole character vector, and a whole number given to %s or %c is a character code; a number that is not whole given to %d, %i, %u, %x or %o is written as %e would; Inf and NaN are written as Inf and NaN. fprintf writes to the Command Window (fid 1, or 2 for the error text) or to the open file fid, and returns the number of bytes.
newline:
    Python: core.py. char(10).
error:
    Python: core.py. Raises a Python exception (MError) holding the identifier and the message, which the try/catch of the compiled program catches. With an identifier first (component:name, no spaces), the message is the format after it applied to the other arguments by sprintf's code; a single argument is the message as written. A struct with message and identifier fields works too; an empty message or struct does nothing.
warning:
    Python: core.py. Writes 'Warning: ' and the message (formatted as error formats it) to the Command Window and keeps it for lastwarn, unless that identifier or 'all' is turned off: warning('off', id) and warning('on', id) keep a table of states.
lastwarn, lasterr:
    Python: core.py. The message and identifier of the last warning written, or of the last error, which is kept whenever try/catch catches one or the Command Window prints one; lastwarn(msg, id) sets them.
MException:
    Python: core.py. An object around a Python MError: the identifier, and the message from the format and the arguments by sprintf's code; its identifier, message, stack and cause properties read from it.
throw, throwAsCaller, rethrow:
    Python: core.py. throw raises a new Python exception with the MException's identifier, message and causes, so the stack starts where it is thrown; rethrow raises the caught one itself, keeping where it came from, and also takes a struct with message and identifier fields.
getReport:
    Python: core.py. The text the Command Window prints for the error: the message with 'Error using' and the stack's lines, without the links.
addCause:
    Python: core.py. Appends the second exception to the first one's list of causes.
assert:
    Python: core.py. When the condition is empty or not all true (the test that if uses), raises 'Assertion failed.' or the message formatted as error formats it.
narginchk, nargoutchk:
    Python: core.py. The number of inputs or outputs the calling function was given, which each compiled function keeps in its workspace, against the limits; outside them, the not-enough or too-many error.
nargin, nargout:
    Python: core.py and compiler.py. In a function the compiler reads them straight from the call: the number of arguments and of outputs it was called with. nargin(f) reads the function file's parameter list (negative when it ends in varargin) or the anonymous function's parameters.
class:
    Python: core.py and values.py. The class name of the value's Python type: double, single and the integer classes from the NumPy type, logical for booleans, char, string, cell, struct, function_handle, or the class of an object.
isa:
    Python: core.py. The value's class compared with the name; 'numeric', 'float' and 'integer' name groups of classes, and an object is also each of its superclasses.
isnumeric, isfloat, isinteger, islogical, ischar, iscell, isstruct, isstring, istext, isobject:
    Python: core.py. A test of the value's class: numeric for double, single and the integer classes; text for char or string; isobject for objects that are not graphics.
isreal:
    Python: core.py. False for a complex value (a NumPy array whose type is complex, even with every imaginary part 0) and for cells, structs, strings, handles and objects; true otherwise.
isempty, isscalar, ismatrix, isvector, isrow, iscolumn, issquare:
    Python: core.py. Tests of the size: no elements; one element; two dimensions; two dimensions with one of them 1 (and at least one element); one row; one column; as many rows as columns.
iscellstr:
    Python: core.py. A cell whose every element is a character row (or empty).
isdiag:
    Python: core.py. diag(diag(A)) == A for every element (numpy.diag twice).
isequal, isequaln:
    Python: core.py. The sizes must match, then: numbers, logicals and text compare element by element with == whatever their classes (so isequal(1, true) is true), strings by their text, cells and structs element by element and field by field, function handles by identity or name, and graphics objects and other handles by the objects they hold. NaN is never equal to NaN except in isequaln.
size:
    Python: core.py. The shape the value holds (NumPy's shape, at least two dimensions); with more outputs than dimensions the extra ones are 1, and the last output takes the product of the dimensions left over.
numel, length, ndims:
    Python: core.py. The number of elements (the product of the sizes), the largest size (0 when any size is 0), and the number of dimensions (at least 2).
isvarname, iskeyword:
    Python: core.py. A regular expression: a letter, then up to 62 letters, digits or underscores, and not one of the keywords; iskeyword looks in the lexer's keyword list, or returns the list.
matlab.lang.makeValidName, genvarname:
    Python: core.py. A valid name is kept. Otherwise white space at the ends is dropped and white space inside is removed with the letter after it made a capital; each other character that is not a letter, digit or underscore becomes an underscore (or is deleted, or becomes 0x and its code in hexadecimal, by ReplacementStyle); the prefix ('x') goes in front of a keyword (whose first letter becomes a capital) or of a name that does not start with a letter; the name is cut to 63 characters. genvarname then adds 1, 2, ... to a name among the exclusions or made already.
exist:
    Python: core.py. 1 for a variable of the calling workspace, 2 for a file found on the path or by name, 5 for a builtin, 7 for a folder, else 0; the second argument limits which kinds are looked for.
clear, clearvars:
    Python: core.py. Deletes names from the workspace's dictionary, with Python's fnmatch for the wildcards * and ? and re.match for -regexp; -except keeps the names given. clear all also empties the globals and the persistent variables, and clear functions the persistent variables, and both make files compile again on their next call.
who, whos:
    Python: core.py. The workspace's names, sorted without regard to case and filtered by the wildcards given. whos adds size, class and bytes: 8 a double, 1 a logical, 2 a character, the NumPy array's own byte count, and for cells and structs their elements' bytes plus a fixed 104 for each; a table its variables', the other value classes their arrays' (and a categorical's names). With -file the variables are a MAT-file's, read as load reads them (matfile.py); one that cannot be read is listed from its header, its bytes its size times its class's element size.
assignin:
    Python: core.py. Stores the value under the name in the base workspace, or in the calling function's, found by walking up Python's call stack to the compiled function that called this one.
evalin:
    Python: core.py. The text compiled and run as eval does, in the base workspace or in the calling function's (found as for assignin).
eval:
    Python: core.py and compiler.py. The text is compiled to Python as a line typed at the prompt would be and run in the calling workspace; when outputs are wanted it is compiled as an assignment to temporary names. When it fails and a second text is given, that one runs instead.
evalc:
    Python: core.py. eval with the Command Window's output kept aside: what the text prints is returned as text instead of shown.
feval:
    Python: core.py and runtime.py. Calls the function handle, or looks the name up as a call does (a local function, a file on the path, then a builtin) and calls it with the arguments. A fit or fittype (curvefit.py) is evaluated instead.
builtin:
    Python: core.py. Calls the builtin of that name from the table of builtins, passing over any file of the same name on the path.
func2str, str2func:
    Python: core.py. The handle's text: an anonymous function as written, a named one without the @. str2func makes a named handle, or compiles '@(x) ...' as a one-line assignment to an anonymous function (anything more is refused).
functions:
    Python: core.py. A struct of the handle's text, its kind (anonymous or simple), its file, and for an anonymous function the values it captured.
deal:
    Python: core.py. Gives the one input to every output, or the inputs to the outputs in order (their numbers must match).
tic, toc:
    Python: core.py. Python's time.perf_counter, a clock with sub-microsecond steps; tic with an output returns the time in microseconds as a uint64, which toc(t) reads.
cputime:
    Python: core.py. Python's time.process_time, the processor time of the engine.
clc:
    Python: core.py. Empties the output not yet shown and tells the page to clear the Command Window.
more, echo:
    Python: core.py. Accepted and ignored.
diary:
    Python: devtools.py and runtime.py. Each piece of output (and each command the Command Window runs) is kept while the diary is on, with links written as their text, and added to the file at the end of each command.
profile:
    Python: devtools.py and runtime.py. While profiling, every compiled statement calls the engine's hook: the time from one statement to the next goes to the first, and to the total of every program function on the stack; a call is counted the first time a function's workspace is seen.
input:
    Python: core.py and runtime.py. Writes the prompt and waits for the page to send the line typed. With 's' the line is returned as text; otherwise it is compiled as an expression in a copy of the base workspace and evaluated, and an error is shown and the question asked again.
keyboard:
    Python: core.py. Hands control to the debugger, which stops in the calling workspace as at a breakpoint.
pause:
    Python: core.py and runtime.py. pause(t) shows the output and figures, then waits t seconds by Python's asyncio.sleep in steps of at most 0.05 s, running the callbacks of the clicks and keys that come in meanwhile and stopping at Ctrl+C; pause alone waits for a key in the Command Window.
exit, quit:
    Python: core.py. An error: a browser tab is not closed by a command.
help:
    Python: core.py and help.py. The same help the Help browser shows, as text; with an output, returned rather than printed.
version, ver, computer:
    Python: core.py. Fixed text naming PyLAB, with Python's, NumPy's and SciPy's version numbers read from the running engine (with an output, ver gives them as a struct array instead); computer is 'PYODIDE'.
ispc, isunix, ismac, isdeployed, usejava:
    Python: core.py. Fixed answers for the engine in the page: isunix is true (Pyodide's file system is Unix-like), the others false.
getenv, setenv:
    Python: core.py. Python's os.environ in the engine.
inputname:
    Python: core.py. Always '' (the names of the arguments are not kept).
mfilename:
    Python: core.py. Walks up Python's call stack to the first frame of compiled code and gives the name of the file it was compiled from (with 'fullpath', its path without .m); '' for a line typed at the prompt.
validateattributes:
    Python: core.py. The class against the list of classes ('numeric', 'float' and 'integer' name groups), then each attribute tested in turn, by the size or by NumPy on the values: 2d, 3d, row, column, scalar, scalartext, vector, square, diag, nonempty, size (NaN for any), numel, ncols, nrows, ndims, binary, even, odd, integer, real, finite, nonnan, nonnegative, nonzero, positive, >, >=, <, <=, increasing, decreasing, nondecreasing and nonincreasing (NaN fails the ordering tests); nonsparse fails for a sparse matrix. The message names the input by the optional function name, variable name and argument number.
onCleanup:
    Python: core.py and runtime.py. An object that calls the function when Python deletes it: when the variable holding it is cleared or the function's workspace goes at its return.
# ---- strfun.py: text ----------------------------------------------------------------------
char:
    Python: strfun.py and values.py. Character arrays hold the characters' codes in a NumPy array of uint16. Numbers become codes: rounded down, negative ones and NaN to 0, and kept within 0 to 65535. Several arguments, a cell or a string array become the rows of a character matrix, the shorter rows padded with blanks. Of a Python object: pycall.py, NumPy's asarray (double), the items, str() or the dict's items.
string:
    Python: strfun.py and strings.py. String arrays are NumPy arrays of Python str objects (None for a missing string). Text converts as it is, each row of a character matrix to one string; a whole number is written in full, any other with 5 significant digits (Python's %.5g), a logical as true or false, and NaN becomes a missing string. Of a Python object: pycall.py, NumPy's asarray (double), the items, str() or the dict's items.
strings:
    Python: strfun.py. A string array of the size given, every element ''.
cellstr:
    Python: strfun.py. Each row of a character matrix, its trailing blanks removed, in a cell of one column; each string of a string array as a character vector in a cell of the same size.
blanks:
    Python: strfun.py. A row of n characters of code 32.
convertStringsToChars, convertCharsToStrings:
    Python: strfun.py. Each argument converted on its own: a string to a character vector (a string array to a cell of them), or a character vector or cell of them to a string array; the other arguments pass unchanged.
num2str:
    Python: strfun.py. A whole number is written in full (an integer type exactly). Any other number is written by Python's %g with max(floor(log10(abs(x))), 0) + 5 significant digits, at most 16 (so 4 decimals between 1 and 10), the exponent with a sign and at least two digits; a matrix gets the digits of its largest element, each column right-aligned, two spaces apart. With a format, each row is written by sprintf and the leading blanks all rows share are removed; with a precision, %.ng.
int2str:
    Python: strfun.py. The values rounded to whole numbers, halves away from zero (as round does), then written as num2str writes them.
mat2str:
    Python: strfun.py. Each element by Python's %.15g (or the precision given): elements separated by spaces, rows by semicolons, in brackets unless there is one element; logical values as true and false, text in quotes, and with 'class' the class name around it.
str2num:
    Python: strfun.py. The text is compiled and run, as a line at the prompt would be, as the assignment of [text] in a workspace of its own, so any expression or function call in it is evaluated; when it fails the result is [] and the second output false.
str2double:
    Python: strfun.py. Regular expressions read each text as a whole: an optional sign, digits (commas between them are ignored), a decimal point, an exponent with e or d, Inf or NaN; or a complex number a+bi or bi. Python's float converts the matched digits. Anything else, and any element of a cell that is not text, gives NaN.
dec2bin, dec2hex, dec2base:
    Python: strfun.py. Each value as a Python integer (exact for 64-bit integers; a fraction cut toward zero), written by format(n, 'b') or format(n, 'X'), or by repeated division by the base with the digits 0-9 and A-Z; padded on the left with zeros to n characters or to the longest of them. dec2bin and dec2hex write negative numbers in two's complement, in the smallest of 8, 16, 32 and 64 bits that holds them all, padded with the sign digit; dec2base refuses them.
bin2dec, hex2dec, base2dec:
    Python: strfun.py. Python's int(s, base) of each text with its blanks taken out, as a double.
num2hex, hex2num:
    Python: strfun.py. Python's struct.pack('>d') and struct.unpack: the eight bytes of the IEEE double, most significant first, as 16 hexadecimal digits (a single's four bytes as 8 digits); hex2num pads shorter texts with zeros on the right.
upper, lower:
    Python: strfun.py. Python's str.upper and str.lower, which change letters of every alphabet, not only A-Z.
strtrim:
    Python: strfun.py. Python's str.strip of white space, null characters and the no-break space at both ends.
deblank:
    Python: strfun.py. Python's str.rstrip of white space and null characters at the end.
reverse:
    Python: strfun.py. The characters in reverse order (Python's s[::-1]).
strip:
    Python: strfun.py. Python's str.strip, lstrip or rstrip, of white space or of the characters given.
pad:
    Python: strfun.py. Python's str.ljust, str.rjust or str.center to the width given (the longest text unless given), with blanks or the character given.
strjust:
    Python: strfun.py. Each row's blanks taken off its ends, and the row set right, left or centred in the width of the matrix.
strlength:
    Python: strfun.py. Python's len of each text: the number of characters, NaN for a missing string.
strcmp, strcmpi, strncmp, strncmpi:
    Python: strfun.py. Python's == on the texts (both lower-cased by str.lower for the i forms), or on their first n characters, which both must have. With a cell or string array they compare element by element, a single text against each; anything that is not text compares false.
matches:
    Python: strfun.py. True where the whole text equals one of the patterns (both lower-cased with 'IgnoreCase').
contains, startsWith, endsWith:
    Python: strfun.py. Python's in, str.startswith and str.endswith, true when any of the patterns is found; 'IgnoreCase' lower-cases text and patterns first.
strfind:
    Python: strfun.py. Python's str.find, started again one character after each hit so that overlapping occurrences are found; the positions from 1, a cell of them for a cell of texts or with 'ForceCellOutput'. An empty pattern gives [].
count:
    Python: strfun.py. Python's str.count for each pattern, added up; occurrences that overlap are counted once.
strtok:
    Python: strfun.py. Skips the delimiters at the start (white space and null unless given), takes the characters up to the next delimiter as the token, and the rest from that delimiter on as the remainder.
strrep:
    Python: strfun.py. Python's str.replace; where occurrences overlap, every one found by str.find (overlapping ones too) is replaced, as the language's strrep does.
replace:
    Python: strfun.py. One regular expression of all the old texts (escaped, the longest first) and re.sub putting in each match's new text, so a replacement is never replaced again.
erase:
    Python: strfun.py. Python's str.replace of each pattern by nothing, the longest pattern first.
extractBefore, extractAfter, extractBetween:
    Python: strfun.py. Python's str.find for the first occurrence of the text, or the positions given, and the slice before, after or between them.
insertAfter, insertBefore:
    Python: strfun.py. Python's str.replace of every occurrence of the text by itself with the new text after or before it, or the new text put in at the position given.
strcat:
    Python: strfun.py. For character arrays the trailing white space of each argument is removed (spaces, tabs, newlines, nulls) and the rest joined. With a cell the texts are joined element by element, a single text repeated; with a string array it is the + of strings, which keeps the white space.
strvcat:
    Python: strfun.py. The texts as the rows of a character matrix padded with blanks; empty texts are left out.
strjoin, join:
    Python: strfun.py and tables.py. join of two tables: a Python dictionary from the keys of B (each row's key values as a tuple) to its row gives the row of B for each row of A. For text, Python's str.join with the delimiter (a space unless given; escapes such as \n become characters in strjoin); a cell of delimiters puts each one in its place. join joins along the rows of a string matrix.
strsplit:
    Python: strfun.py. Python's re.split on one regular expression of the delimiters (escaped, the longest first; white space unless given), with a run of delimiters counted as one unless 'CollapseDelimiters' is false; 'DelimiterType', 'RegularExpression' takes them as patterns. The second output is the delimiters found, by re.findall.
split:
    Python: strfun.py. Python's re.split by the delimiters, or by runs of white space with the text's ends trimmed first; a string column, or for several texts a string matrix with one row each.
splitlines:
    Python: strfun.py. Python's re.split on \r\n, \n or \r.
compose:
    Python: strfun.py and fmt.py. sprintf's code applied to each row of the arguments in turn, one string for each row.
isspace, isletter:
    Python: strfun.py. A test of each character: isletter is Python's str.isalpha, true for the letters of every alphabet; isspace is true for space, tab, newline, carriage return, form feed and vertical tab.
isstrprop:
    Python: strfun.py. A test of each character: Python's str.isalpha, str.isalnum, str.islower, str.isupper and str.isprintable for 'alpha', 'alphanum', 'lower', 'upper' and 'print'; the digits 0-9, the hexadecimal digits and the six white-space characters by sets; 'punct' is printable but neither alphanumeric nor space, 'graphic' printable but not space, and 'cntrl' the codes below 32 and 127.
validatestring:
    Python: strfun.py. The options that start with the text, compared without regard to case; an exact match wins, otherwise the first of them, and none is an error.
regexp, regexpi:
    Python: strfun.py. Python's re module. The pattern is first put in Python's dialect, (?<name>...) as (?P<name>...) and \< and \> as \b, and compiled with re.S (the dot matches a newline) unless 'dotexceptnewline', re.I for regexpi and 'ignorecase', re.M for 'lineanchors' and re.X for 'freespacing'. finditer gives the matches, from which start, end, tokenextents, match, tokens, names and split are built, positions from 1; 'once' keeps the first match. Python's dialect is not the same in every detail: a lookbehind, for instance, must have a fixed length.
regexprep:
    Python: strfun.py. re.sub of each pattern in turn (put in Python's dialect as regexp does), with $1 and $<name> in the replacement written as \g<1> and \g<name>; 'once' replaces the first match only.
regexptranslate:
    Python: strfun.py. 'escape' is Python's re.escape; 'wildcard' escapes each dot and writes * as .* and ? as a single dot.
symvar:
    Python: strfun.py. A regular expression finds the names in the text, passing over quoted text and numbers; i, j, pi, Inf, NaN, eps and every name that resolves to a function or a file on the path are left out, and the rest sorted.
sscanf:
    Python: strfun.py and iofun.py. The code of fscanf, reading the text instead of a file.
strmatch:
    Python: strfun.py. The rows (or texts) that start with the text, or with 'exact' that equal it once trailing blanks and nulls are taken off; their numbers as a column.
# ---- iofun.py: files and folders ----------------------------------------------------------------
pwd, cd:
    Python: iofun.py. Files live in Pyodide's file system, held in memory, whose home folder /home/user the page keeps in the browser's storage (IndexedDB). The engine keeps the current folder itself and joins relative names to it (os.path.join, then os.path.normpath); cd checks the folder with os.path.isdir and makes program files be looked up again.
userpath, matlabroot:
    Python: iofun.py. Fixed folders: the home folder /home/user, and /pylab.
mkdir, rmdir:
    Python: iofun.py. Python's os.makedirs, which makes missing parent folders too (a folder that exists gives a warning), and os.rmdir, or shutil.rmtree with 's'.
delete:
    Python: iofun.py. Python's glob.glob of the name (the wildcards * and ?) and os.remove of each file found. Graphics objects and timers, given as handles or handle numbers, are deleted instead.
copyfile, movefile:
    Python: iofun.py. Python's glob.glob of the source, then shutil.copy2 for each file (shutil.copytree for a folder) or shutil.move.
zip, unzip:
    Python: iofun.py. Python's zipfile. The files are found by name (a name that is there taken as it is, else as a pattern for glob.glob), folders walked by os.walk, and each written deflated under its path from the root folder. unzip copies each entry out with shutil.copyfileobj, leaving out any whose path would end outside the folder.
gzip, gunzip:
    Python: iofun.py. Python's gzip module, one file at a time through shutil.copyfileobj.
tar, untar:
    Python: iofun.py. Python's tarfile, compressed with gzip for a .tgz or .tar.gz name. untar takes only files and folders, each through tarfile's 'data' filter, which refuses absolute paths and entries that would land outside the folder.
dir, ls:
    Python: iofun.py. Python's os.listdir of a folder (with . and ..) or glob.glob of a pattern, sorted without regard to case, and os.stat for each entry's size and time; datenum is the modification time in days from year 0 (seconds / 86400 + 719529).
what:
    Python: iofun.py. os.listdir of the folder, the .m and .mat files picked out by their endings.
fullfile:
    Python: iofun.py. The parts joined with /, and repeated slashes made one.
fileparts:
    Python: iofun.py. Python's os.path.split and os.path.splitext: the folder, the name, and the extension from the last dot (a name such as .bashrc is all extension).
filesep, pathsep:
    Python: iofun.py. '/' and ':', as on Unix.
tempdir, tempname:
    Python: iofun.py. /tmp/, and a name there made of 'tp' and 12 random hexadecimal digits from Python's uuid.uuid4.
isfile, isfolder, isdir:
    Python: iofun.py. Python's os.path.isfile and os.path.isdir of the name joined to the current folder.
addpath, rmpath, path, genpath:
    Python: iofun.py and runtime.py. The path is a Python list of folders searched after the current folder: addpath puts folders first (last with -end), each folder at most once; rmpath takes them out; both make program files be looked up again. genpath walks the tree with os.walk, leaving out the folders that start with @, + or . and the private ones.
rehash:
    Python: iofun.py. Makes every program file be looked up and compiled again at its next call; changed files are noticed anyway.
which:
    Python: iofun.py and runtime.py. The lookup a call makes: the path of the program file found in the current folder or on the path, or built-in for a builtin.
type:
    Python: iofun.py. The file read with Python's open (UTF-8) and printed, or returned with an output.
edit:
    Python: iofun.py. Tells the page to open the file in the Editor; a .m file that does not exist is made empty first.
run:
    Python: iofun.py. Changes to the script's folder, compiles and runs the file (a script in the calling workspace, a function with no arguments), and changes back even when it fails. A test suite, test object or runner: unittests.py, as runtests. A MultiStart or GlobalSearch object: globalopt.py.
web:
    Python: iofun.py. Tells the page to open the address in a new browser tab (window.open).
fopen, fclose:
    Python: iofun.py. Python's open in binary mode ('r', 'w', 'a' and their + forms; a t is ignored). The file objects are kept in a dictionary under identifiers from 3 up, with the encoding given (UTF-8 unless given) that the text functions use; fclose closes one or all of them. fopen(fid) gives the name, mode, machine format and encoding of an open file ("stdin", "stdout" and "stderr" for 0, 1 and 2, empty texts for an identifier that is not open).
fgetl, fgets:
    Python: iofun.py. Python's readline on the binary file, decoded by the file's encoding (bytes that do not decode become replacement characters); fgetl drops the line ending. -1 at the end of the file.
feof:
    Python: iofun.py. Tries to read one byte and moves back when there was one.
frewind, ftell, fseek:
    Python: iofun.py. The file object's seek and tell, with 'bof', 'cof' and 'eof' (or -1, 0 and 1) as Python's whence 0, 1 and 2.
ferror:
    Python: iofun.py. Always '' and 0: a failure raises an error at once instead.
fread:
    Python: iofun.py. The bytes read and turned into numbers by numpy.frombuffer with the precision's NumPy type (uint8 unless given; 'ieee-be' reverses the byte order), into a column or the size given (filled down the columns, padded with zeros). The result is double unless the precision names another class ('*int16', 'int16=>int16' or '=>char').
fwrite:
    Python: iofun.py. The elements in column order converted to the precision's type (uint8 unless given; integers rounded and saturated as int8() and the others do) and written as their bytes, NumPy's tobytes in the machine's order (little-endian).
fileread:
    Python: iofun.py. The whole file decoded as UTF-8, or as Latin-1 when it is not valid UTF-8.
readlines, writelines:
    Python: iofun.py. The file's text split at the newlines (a carriage return before one is dropped) into a string column; writelines writes the lines in UTF-8 with a newline after each.
fscanf:
    Python: iofun.py. The rest of the file decoded as text, then the format applied by regular expressions, conversion by conversion and again from its start while the text matches: %d, %i and %u whole numbers, %f, %e and %g numbers (Inf, NaN and a d exponent too), %x and %o, %s a word, %c characters and %[...] a set of them. White space in the format matches any white space, and %*... reads without keeping. The numbers fill a column (or the size given, down the columns); when only %s and %c were read the result is text.
textscan:
    Python: iofun.py. A scanner of its own: the format is read into conversions (%f, %f32, %n, %d, %d8 to %d64, %u to %u64, %s, %q, %c, %[...] and %[^...], each with a width, a precision and * to skip) and literal text, and applied to the text (or the rest of the file) again and again, N times or to the end. White space before a field is skipped; with delimiters (characters, or strings in a cell) a field ends at one, two delimiters in a row make an empty field (EmptyValue, NaN unless given, converted to the column's class), and a line end ends a row, its missing fields empty. Numbers are matched by a regular expression (signs, decimals, exponents with ExpChars, Inf, NaN, and a + bi), integers converted exactly with rounding and saturation. A field that does not read stops the scan (ReturnOnError) and the columns read so far come back, of unequal length; the end of the text pads its last row. HeaderLines, TreatAsEmpty, CommentStyle (to the end of the line, or between two markers), MultipleDelimsAsOne, Whitespace, EndOfLine and CollectOutput (neighbouring columns of one class joined) are handled as they read. An empty format reads as many %f as the first line has numbers. The second output is the position where reading stopped; a file is left at that position.
readmatrix, csvread, dlmread:
    Python: iofun.py. Each line split by the delimiter given, or else by the first of comma, tab and semicolon it holds (white space when none), and each field read by Python's float, NaN when it is empty or text. Leading lines that are all text are dropped, and short rows padded with NaN.
writematrix, csvwrite, dlmwrite, writecell:
    Python: iofun.py. One line for each row, the elements joined by the delimiter (a comma unless given): whole numbers in full, others by %.15g, text as it is.
readcell:
    Python: iofun.py. Each line that is not blank split at the commas; a field that Python's float reads becomes a number, any other a character vector.
save:
    Python: iofun.py, matwrite.py and matobjects.py. A file with objects (tables, timetables, datetimes, durations, calendarDurations, categoricals, string arrays) is written by PyLAB's own Level 5 writer: each object a reference into the file's object data (its subsystem), where its saved properties are kept, in the layout the open-source mat-io reader documents (version 4 of the metadata); the rest as SciPy would write it. Otherwise SciPy's scipy.io.savemat writes a Level 5 MAT-file, compressed for -v7 (the default, and for -v7.3, as SciPy does not write HDF5), uncompressed for -v6, or a Level 4 file for -v4; text, cells and structs go to it as NumPy arrays of strings and objects and as dictionaries. -append reads the file first and writes all of it again, refusing when a variable it holds could not be read back. -ascii writes the numbers as text by %.7e (%.16e with -double). Function handles and objects are not saved.
load:
    Python: iofun.py and matfile.py. MAT-files are read by PyLAB's own reader: Level 4 and Level 5 files, compressed or not, in either byte order, with tables, timetables, datetimes, durations, calendarDurations, categoricals and string arrays made again from their saved properties in the file's object data (matobjects.py; a datetime's milliseconds since 1970 as a double-double, a categorical's codes and names, a table's variables, names and properties, a timetable's struct with its row times or its start and step); -v7.3 files are HDF5 and are read through h5py, which Pyodide loads the first time. Nothing in a file is trusted: sizes are checked against the data, inflated data is capped and nesting is limited, and a variable that cannot be read is reported while the others are read. Any other file is read as readmatrix reads it, into a variable named after the file. coastlines, when no such file is found, is Natural Earth's coastline GeoJSON (geodata.py, fetched by pyfetch once a session), its lines joined into coastlat and coastlon with NaN between them.
matfile:
    Python: iofun.py. All the variables of the MAT-file read at once, as load reads them, into a struct.
importdata:
    Python: iofun.py. A MAT-file read as load reads it (one variable alone, several in a struct); any other file read as readmatrix reads it.
textread:
    Python: iofun.py. The whole file, after the header lines and comments are taken out, read with the format again and again: %d, %f, %n and %u numbers (an empty field gets the empty value), %s words, %q quoted text, %c characters and %[...] sets, with the literal text matched. One output for each conversion that is not skipped with *.
# ---- cellfun.py: cells, structs and maps ---------------------------------------------------------
cell:
    Python: cellfun.py and values.py. A cell array is a NumPy array of Python objects, each element any value; cell(n) fills one of the size given with []. Of a Python object: pycall.py, NumPy's asarray (double), the items, str() or the dict's items.
num2cell:
    Python: cellfun.py. Each element in a cell of its own, keeping its class (a struct's elements, a string's strings, a character's characters); with dims, the slices along those dimensions instead.
cell2mat:
    Python: cellfun.py and ops.py. Each row of the cell concatenated as [a, b, ...] would be, then the rows stacked as [r1; r2; ...]; a cell of more dimensions has its pages joined the same way along the third dimension and on. Cells that hold cells or function handles are refused.
cell2struct:
    Python: cellfun.py. The cell's elements along the dimension given (the first unless given) become the named fields, and the other dimensions the struct array's size.
struct2cell:
    Python: cellfun.py. The fields' values as a cell with one row for each field (and the struct array's dimensions after it).
struct:
    Python: cellfun.py and values.py. A struct array is a Python dictionary from field names, in their order, to NumPy object arrays of the struct's size. A cell value spreads over a struct array of the cell's size, a 1-by-1 cell gives its content to every element, and any other value goes to every element. Of a Python object: pycall.py, NumPy's asarray (double), the items, str() or the dict's items.
fieldnames:
    Python: cellfun.py. The dictionary's keys in their order, as a column cell (an object's property names).
isfield, isprop:
    Python: cellfun.py. Whether the name is a key of the struct's dictionary, or one of the object's property names.
rmfield:
    Python: cellfun.py. A new struct whose dictionary leaves out the names given; a missing name is an error.
setfield, getfield:
    Python: cellfun.py and index.py. The assignment s.(a).(b) = v and the reading s.(a).(b), with cells of subscripts as indices in between, by the code that runs those expressions.
orderfields:
    Python: cellfun.py. The fields in Python's sorted order of the names (by the characters' codes, so capitals first), or in the order of another struct, a cell of names or a permutation; the second output is the permutation.
cellfun, arrayfun:
    Python: cellfun.py. The function is called once for each element, in column order, with the elements of all the inputs at that position; each call is awaited, so a function that pauses or draws works, and the page checks for Ctrl+C between calls. With UniformOutput (the default) every result must be a scalar, and they are gathered into an array of their class (double and logical may mix); otherwise into a cell of the input's size. An ErrorHandler is called with a struct of message, identifier and index when a call fails. For cellfun, the names 'isempty', 'islogical', 'isreal', 'length', 'ndims', 'prodofsize', 'numel', 'size' and 'isclass' given as text are computed directly, without calls.
structfun:
    Python: cellfun.py. The function called on each field's value of a scalar struct in turn; the results as a column, or with UniformOutput false as a struct with the same fields.
dictionary, insert, lookup, numEntries, isConfigured, types, entries:
    Python: dictionaries.py. A Python dictionary (in the order keys were put in) inside a value object: every assignment makes a new one, so copies never share. Text keys are kept as Python strings, number keys as floats (logical ones as bools); each value is one 1-by-1 element of the values' class, and several looked up together are joined by horzcat and shaped as the keys were. entries builds a table through table().
enumeration:
    Python: classfun.py and classdef.py. The enumeration block's lines are cut at their commas into members with the text of their arguments. Each member is made once, when first asked for, by the class's constructor with those arguments evaluated, or for a class based on a number class, as that number (by that class's conversion function). Being one object each, members compare by identity, and arrays of them (an object array) by their names; char, string, cellstr, ismember and the number classes are the class's methods unless it writes its own.
import:
    Python: classfun.py and runtime.py. The names are kept on the workspace of the function (or the Command Window) that ran the import; a call of a name that is no variable then looks for pkg.name (for pkg.*, the first package that has it, the latest import first) before the path and the builtins. pkg.name is the file +pkg/name.m (or +pkg/@name/name.m) in a folder of the path.
labindex, spmdIndex, numlabs, spmdSize:
    Python: parallel.py. 1: an spmd block's body runs once, here.
containers.Map:
    Python: cellfun.py. A Python dictionary inside a handle object, so every copy of the map is the same map: keys are Python strings (KeyType 'char', the default) or floats (when the keys given are numbers or KeyType names a numeric class), each value any value.
keys, values:
    Python: cellfun.py. The dictionary's keys in Python's sorted order (text by the characters' codes, numbers by value), and the values in the order of their keys or of the keys given.
isKey, remove:
    Python: cellfun.py. Python's in and del on the map's dictionary, for one key or a cell of them.
# ---- statdesc.py: descriptive statistics ---------------------------------------------------------
grp2idx:
    Python: statdesc.py. For numbers, numpy.unique of the values without NaN, and each observation's group is its value's place in that sorted list; for text, the groups in the order they first appear, with empty text missing (NaN). A cell of grouping variables groups by all of them together, the labels joined by commas.
trimmean:
    Python: statdesc.py. Each vector sorted (NaN left out) and k = n*percent/200 values taken off each end, k rounded to the nearest whole number ('round', the default) or down ('floor'); 'weighted' gives the values at each cut a fractional weight instead. The mean of the rest, or the median when nothing would be left.
geomean, harmmean:
    Python: statdesc.py. exp(mean(log(x))) and n./sum(1./x) along the first dimension whose size is not 1, by NumPy.
mad:
    Python: statdesc.py. The mean of abs(x - mean(x)), or with flag 1 the median of abs(x - median(x)), with NaN left out as missing (NumPy's nanmean and nanmedian), along a dimension, a vector of them or 'all'; single stays single.
moment:
    Python: statdesc.py. mean((x - mean(x)).^k): the central moment, divided by n, along a dimension, a vector of them or 'all'.
zscore:
    Python: statdesc.py. (x - mean(x))./std(x) by NumPy along a dimension, a vector of them or 'all', std with n - 1 (n with flag 1); where the std is 0 it divides by 1, so a vector with no spread gives zeros. The mean and std are the second and third outputs; integers give doubles.
nanmean, nanmedian, nanstd, nanvar:
    Python: statdesc.py. numpy.mean, numpy.median, numpy.std and numpy.var (n - 1, or n with flag 1) of each vector with its NaN taken out; NaN when nothing is left.
nansum:
    Python: statdesc.py. numpy.nansum, which counts NaN as 0.
nanmax, nanmin:
    Python: statdesc.py and datafun.py. max and min, which leave NaN out anyway.
tabulate:
    Python: statdesc.py. For whole numbers from 1, the count of every value from 1 to the largest, those that never occur included; for other numbers, of each distinct value (numpy.unique); for text, of each group in the order it first appears (numpy.bincount). The percentages are of the number of values.
grpstats:
    Python: statdesc.py. Each column split into the groups (as grp2idx groups), NaN left out, and each statistic computed by NumPy: mean, sem (std/sqrt(n)), numel, std and var (n - 1), min, max, range, median, and gname for the labels. meanci and predci are the mean plus and minus t*std/sqrt(n) and t*std*sqrt(1 + 1/n), with t = scipy.stats.t.ppf(1 - alpha/2, n - 1).
ecdf:
    Python: statdesc.py. numpy.unique with counts gives the steps: F = cumsum(counts)/n at each distinct value, from 0 before the smallest. The bounds are Greenwood's: the variance (1 - F)^2*cumsum(d./(r.*(r - d))), with d the count at each value and r the number at risk there, and F plus and minus z times its square root, z from scipy.stats.norm.ppf, kept within [0, 1]. 'survivor' gives 1 - F and 'cumulative hazard' -log(1 - F); with no output it draws the steps.
ksdensity:
    Python: statdesc.py and distributions.py. The mean of K((x - x_i)/h)/h over the data, the kernel (normal, box, triangle or Epanechnikov) scaled to unit variance so that the bandwidth h is its standard deviation. h is, unless given, the rule for normal data with a robust spread: median(abs(x - median(x)))/0.6745*(4/(3n))^(1/5). The 100 points span the data and 3h beyond. For 'positive' support the estimate is made on log(x), for [lo hi] on log((x - lo)./(hi - x)), and carried back by the derivative of the transformation. 'cdf', 'survivor' and 'cumulative hazard' use the kernel's distribution function, and 'icdf' finds each quantile by scipy.optimize.brentq.
corr:
    Python: statdesc.py. Pearson's r by numpy.corrcoef for each pair of columns, the p-value from t = r*sqrt((n - 2)/(1 - r^2)) and the survival function of scipy.stats.t. Spearman's is Pearson's on the ranks (scipy.stats.rankdata, ties averaged); Kendall's is scipy.stats.kendalltau (tau-b) with its own p-value. 'Rows', 'complete' drops the rows with any NaN and 'pairwise' those of each pair; a one-sided 'Tail' halves the two-sided p-value on the side of r. Rows are observations and columns variables, a row vector too (so its correlations are NaN); single in gives single out.
bootstrp:
    Python: statdesc.py. For each of the nboot samples, n row numbers drawn with replacement from rand's generator, the data's rows (or a vector's elements) taken with them, and the statistic called on them; each result is a row of the output, and the second output holds the row numbers.
jackknife:
    Python: statdesc.py. The statistic called n times, each time with one row (or element) of the data left out; the results as rows.
# ---- stattests.py: hypothesis tests ---------------------------------------------------------------
ttest:
    Python: stattests.py. For each column (NaN left out), t = (mean(x) - m)/(std(x)/sqrt(n)), and the p-value from the distribution and survival functions of scipy.stats.t with n - 1 degrees of freedom (twice the smaller tail for 'both'); the interval is the mean plus and minus scipy.stats.t.ppf(1 - alpha/2, n - 1) standard errors. With y the differences x - y are tested: the paired test.
ttest2:
    Python: stattests.py. With equal variances (the default) the pooled standard deviation sp = sqrt(((nx - 1)vx + (ny - 1)vy)/(nx + ny - 2)) gives se = sp*sqrt(1/nx + 1/ny); with 'unequal', Welch's se = sqrt(vx/nx + vy/ny) and Satterthwaite's degrees of freedom. t = (mean(x) - mean(y))/se, with the p-value and the interval for the difference from scipy.stats.t.
ztest:
    Python: stattests.py. z = (mean(x) - m)/(sigma/sqrt(n)), with the p-value and the interval from scipy.stats.norm.
vartest:
    Python: stattests.py. chi2 = (n - 1)*var(x)/v0, with the p-value from scipy.stats.chi2 with n - 1 degrees of freedom; the interval is (n - 1)*var(x) over its quantiles.
vartest2:
    Python: stattests.py. F = var(x)/var(y), with the p-value from scipy.stats.f with nx - 1 and ny - 1 degrees of freedom; the interval is F over its quantiles.
vartestn:
    Python: stattests.py. Bartlett's statistic, ((N - k)*log(sp^2) - sum((n_i - 1)*log(s_i^2)))/C with C = 1 + (sum(1./(n_i - 1)) - 1/(N - k))/(3(k - 1)), and its p-value from scipy.stats.chi2 with k - 1 degrees of freedom. The Levene tests (squared or absolute deviations from the group means), Brown-Forsythe's (absolute deviations from the medians) and O'Brien's (squared deviations transformed with w = 0.5) are a one-way analysis of variance of those deviations.
signtest:
    Python: stattests.py. The number of positive differences among the nonzero ones. Below 100 of them the exact p-value from scipy.stats.binom with probability 1/2; otherwise the normal approximation with a continuity correction of 1/2.
signrank:
    Python: stattests.py. Zero differences dropped, the ranks of abs(d) by scipy.stats.rankdata (ties averaged), and W the sum of the positive differences' ranks. For n up to 15 the exact null distribution, built up a rank at a time over all 2^n choices of signs (doubled ranks keep ties whole); otherwise the normal approximation with mean n(n + 1)/4, the variance corrected for ties, and a continuity correction of 1/2.
ranksum:
    Python: stattests.py. The sum of the first sample's ranks among both samples (scipy.stats.rankdata, ties averaged). When the smaller sample has fewer than 10 values and both together fewer than 20, the exact p-value: the number of ways of choosing nx of the ranks for each sum, counted a rank at a time. Otherwise the normal approximation with mean nx(N + 1)/2, the variance corrected for ties, and a continuity correction of 1/2.
kstest:
    Python: stattests.py. scipy.stats.kstest of the data against the standard normal distribution, a distribution object's cdf, or a two-column table [x F(x)] interpolated by numpy.interp: the largest distance between the data's empirical distribution and the hypothesized one, with SciPy's exact or asymptotic p-value. The critical value is from scipy.stats.kstwo (both tails) or scipy.stats.ksone (one tail).
kstest2:
    Python: stattests.py. Both empirical distributions evaluated at every value by numpy.searchsorted, the statistic d their largest difference (one way for 'larger' and 'smaller'). The p-value is the asymptotic Kolmogorov series 2*sum((-1)^(j - 1)*exp(-2*j^2*lambda^2)), j = 1 to 100, with lambda = (sqrt(n) + 0.12 + 0.11/sqrt(n))*d and n = n1*n2/(n1 + n2); one-sided, exp(-2*lambda^2).
lillietest:
    Python: stattests.py. The Kolmogorov-Smirnov distance from the normal distribution with the data's mean and std. Its p-value is Dallal and Wilkinson's approximation below 0.1 and Stephens' polynomials above, and the critical value is where that p-value equals alpha (scipy.optimize.brentq). For 'exp' and 'ev' the null distribution is simulated: 20000 samples of the same size (fewer for large ones, at least 2000) from a NumPy generator with a fixed seed, each fitted and its distance taken, and p = (the number at least as large + 1)/(samples + 1).
jbtest:
    Python: stattests.py. JB = n/6*(s^2 + (k - 3)^2/4), with the skewness s and kurtosis k from the central moments (divided by n). For n up to 2000 the p-value is simulated from normal samples of the same size with a fixed seed, so the same data give the same p-value; above that, scipy.stats.chi2 with 2 degrees of freedom.
adtest:
    Python: stattests.py. A^2 = -n - sum((2i - 1)*(log(z_i) + log(1 - z_(n+1-i))))/n of the sorted probabilities z = F(x). For the normal and lognormal distributions (parameters estimated) and the exponential, the p-value from Stephens' approximations with the statistic scaled by 1 + 0.75/n + 2.25/n^2 or 1 + 0.6/n; for the extreme value and Weibull distributions (fitted by maximum likelihood) and for a distribution object given in full, from a null distribution simulated with a fixed seed.
chi2gof:
    Python: stattests.py. The data counted by numpy.histogram in 10 bins of equal width, or the edges or centres given; the expected counts from the hypothesized cdf at the edges (a normal distribution with the data's mean and std unless given), the outer bins taking the tails. Bins expecting fewer than 5 are joined to a neighbour, the ends inward first. chi2 = sum((O - E).^2./E), with the p-value from scipy.stats.chi2 with the number of bins - 1 - the number of estimated parameters degrees of freedom.
runstest:
    Python: stattests.py. The values above and below the median (or v; values equal to it are dropped), and the number of runs. Below 50 values the exact distribution of the number of runs, from binomial coefficients; otherwise the normal approximation with mean 1 + 2*n1*n0/n and its variance, with a continuity correction of 1/2.
anova1:
    Python: stattests.py. Sums of squares by NumPy, between the groups sum(n_i*(mean_i - mean)^2) and within them sum((x - mean_i)^2); F is the ratio of their mean squares, with the p-value from the survival function of scipy.stats.f. The table is printed and a box plot drawn unless 'off'.
anova2:
    Python: stattests.py. The balanced layout with reps observations in each cell: the sums of squares of the columns, the rows, their interaction (when reps > 1) and the error from the means, by NumPy, and each F against the error mean square with the p-value from scipy.stats.f.
kruskalwallis:
    Python: stattests.py. The one-way analysis on the ranks of all the data (scipy.stats.rankdata, ties averaged): H is the ranks' sum of squares between the groups divided by their total sum of squares over N - 1, which corrects for ties, with the p-value from scipy.stats.chi2 with k - 1 degrees of freedom.
friedman:
    Python: stattests.py. The data ranked within each block of rows (scipy.stats.rankdata); the columns' sum of squares of the ranks divided by the ranks' variance, total sum of squares/(m*(reps*c - 1)), with the p-value from scipy.stats.chi2 with c - 1 degrees of freedom.
multcompare:
    Python: stattests.py. Every pair of the group means (or mean ranks) from anova1, kruskalwallis or friedman: the difference plus and minus c times its standard error, which comes from the pooled error (for ranks from their variance N(N + 1)/12, corrected for ties). c is from scipy.stats.studentized_range for Tukey-Kramer (the default), from scipy.stats.t with alpha divided by the number of pairs for Bonferroni or with 1 - (1 - alpha)^(1/pairs) for Dunn-Sidak, sqrt((k - 1)*F) for Scheffe, and the plain t for 'lsd'; the p-values come the same way. The plot gives each mean an interval of half-width c*se/sqrt(2), so that two intervals that do not overlap differ.
crosstab:
    Python: stattests.py. The groups of each variable (as grp2idx makes them) and the table of counts of each combination; the chi-square test of independence with the expected counts from the margins, chi2 = sum((O - E).^2./E), and the p-value from scipy.stats.chi2 with prod(sizes) - 1 - sum(sizes - 1) degrees of freedom.
fishertest:
    Python: stattests.py. scipy.stats.fisher_exact on the 2-by-2 table: the hypergeometric probabilities of all the tables with the same margins. The odds ratio is ad/(bc), with the interval exp(log(OR) plus and minus z*sqrt(1/a + 1/b + 1/c + 1/d)).
# ---- statplots.py: statistical plots ---------------------------------------------------------------
boxplot:
    Python: statplots.py. For each group the quartiles as quantile computes them; the whiskers reach the most extreme values within 1.5 (or 'Whisker') times the box's interquartile range, and the values beyond are the outliers. A notch is the median plus and minus 1.57*IQR/sqrt(n) (McGill, Tukey and Larsen's comparison interval). The parts are ordinary lines (patches when filled) with the Tags 'Box', 'Median', 'Upper Whisker', 'Lower Whisker', 'Upper Adjacent Value', 'Lower Adjacent Value' and 'Outliers'.
gscatter:
    Python: statplots.py. One line object of markers without a line for each group (as grp2idx makes them), with the colours, markers and sizes given taken in turn, and a legend of the groups.
gplotmatrix, plotmatrix:
    Python: statplots.py. The current figure filled with a grid of axes, a scatter plot of each column of Y (or X) against each column of X; for plotmatrix(X) a histogram of each column on the diagonal, and for gplotmatrix the groups' distributions there (stairs, histograms or bars) or the variables' names.
scatterhist:
    Python: statplots.py. A scatter plot with histograms of x and y along its sides in axes of their own, the bins chosen as histogram chooses them; 'Kernel', 'on' draws kernel density estimates instead (ksdensity's normal kernel and bandwidth).
histfit:
    Python: statplots.py and distributions.py. Bars of the counts in ceil(sqrt(n)) bins of equal width, and the density of the distribution fitted to the data as fitdist fits it (normal unless named), times n and the bin width; for a discrete distribution the count of each whole number and n times its probability.
normplot:
    Python: statplots.py. The sorted data against the standard normal quantiles of (i - 0.5)/n (scipy.stats.norm.ppf), the vertical axis marked with the probabilities; the line through the quartiles is solid between them and dashed out to the ends of the data.
qqplot:
    Python: statplots.py. The sorted data against the quantiles of (i - 0.5)/n of the standard normal distribution or of the distribution object given (its icdf), or against a second sample, the larger sample's quantiles taken at the smaller one's points; with the line through the quartiles.
cdfplot:
    Python: statplots.py. The empirical distribution function as steps: numpy.unique with counts, and cumsum(counts)/n. The second output holds the minimum, maximum, mean, median and std.
lsline:
    Python: statplots.py. For each line of markers without a line style, or scatter series, in the axes: the least-squares line by numpy.polyfit of degree 1, drawn from the smallest to the largest x.
refline:
    Python: statplots.py. The line y = m*x + b across the axes' x-limits; without arguments, lsline.
refcurve:
    Python: statplots.py. The polynomial by numpy.polyval at 200 points across the axes' x-limits.
# ---- distributions.py: what the families share (each family's functions are in _distribution_how) ----
normfit:
    Python: distributions.py. For each column (NaN left out), the mean and the std with n - 1. The interval for mu is the mean plus and minus scipy.stats.t.ppf(1 - alpha/2, n - 1)*s/sqrt(n), and for sigma s*sqrt((n - 1)./chi2inv([1 - alpha/2, alpha/2], n - 1)), from scipy.stats.chi2.
unifit:
    Python: distributions.py. a = min(x) and b = max(x), the maximum likelihood estimates, with the intervals [b - (b - a)/alpha^(1/n), a] for a and [b, a + (b - a)/alpha^(1/n)] for b.
binofit:
    Python: distributions.py. p = x/n, with the Clopper-Pearson interval from the quantiles of scipy.stats.beta: beta.ppf(alpha/2, x, n - x + 1) to beta.ppf(1 - alpha/2, x + 1, n - x), and 0 or 1 at the ends.
pdf, cdf, icdf:
    Python: distributions.py. With a name, the distribution is looked up by its whole name, its prefix (norm) or its makedist name, in any case, and the value is the one normpdf, normcdf and norminv and the others give. With a distribution object, its own SciPy distribution's pdf (pmf when discrete), cdf (sf with 'upper') or ppf. A truncated object's values are taken between its limits: pdf/(F(hi) - F(lo)), (F(x) - F(lo))/(F(hi) - F(lo)), and the ppf of F(lo) + p*(F(hi) - F(lo)). Of a Gaussian mixture: mlunsup.py, the weighted sum of the densities of its components.
random:
    Python: distributions.py. With a name, as normrnd and the others draw; with an object, its SciPy distribution's rvs from rand's generator, or for a truncated object the ppf of uniform numbers between F(lo) and F(hi). Of a Gaussian mixture: mlunsup.py, a component drawn by its proportion, then a normal by its Cholesky factor.
makedist:
    Python: distributions.py. An object holding the distribution and the values of its parameters (the defaults for those not given). The families are the scipy.stats distributions the functions of each family use, and for the ones with objects only: Logistic (scipy.stats.logistic), Loglogistic (scipy.stats.fisk), InverseGaussian (scipy.stats.invgauss), Nakagami (scipy.stats.nakagami), Rician (scipy.stats.rice), BirnbaumSaunders (scipy.stats.fatiguelife), Burr (scipy.stats.burr12), HalfNormal (scipy.stats.halfnorm), tLocationScale (scipy.stats.t with a location and scale), Triangular (scipy.stats.triang) and Loguniform (scipy.stats.loguniform). Its mean, median, std, var and iqr come from SciPy's stats and ppf.
fitdist:
    Python: distributions.py. The estimates the fit functions make: normfit's for the normal and the lognormal (on log(x)), closed forms for the exponential, Poisson, Rayleigh, uniform, inverse Gaussian and half normal, and otherwise SciPy's maximum likelihood fit of the family (its fit method, with a location held at 0 where the family has none). The intervals of those are Wald intervals from the inverse of the Hessian of the negative log-likelihood, by central differences. 'Kernel' makes a kernel density object, estimated as ksdensity estimates, and 'By' fits each group.
mle:
    Python: distributions.py. The maximum likelihood estimates fitdist makes, except that the normal's and lognormal's sigma divide by n, as the likelihood's own estimate does; the binomial needs 'NTrials' (p = mean(x)/N with the Clopper-Pearson interval), the geometric gives p = 1/(1 + mean(x)) and the discrete uniform max(x).
paramci:
    Python: distributions.py. The intervals of the object's fit (those fitdist made, made again for another alpha); for an object from makedist, the values themselves.
negloglik:
    Python: distributions.py. -sum(log(pdf(data))) over the data the object was fitted to.
truncate:
    Python: distributions.py. A copy of the object with the limits: its pdf, cdf, icdf and random are then taken between them (see pdf), and its mean and variance by SciPy's expect with conditional=True, a numerical integration between the limits.
mvnpdf, mvncdf:
    Python: distributions.py. scipy.stats.multivariate_normal with the mean (zeros unless given) and the covariance (the identity unless given; a row is taken as a diagonal): the pdf from a factorisation of Sigma, and the cdf by SciPy's randomized quasi-Monte Carlo integration (Genz's method), to about 1e-5.
mvnrnd:
    Python: distributions.py. mu + z*L', with z standard normal numbers from rand's generator and L the Cholesky factor of Sigma (numpy.linalg.cholesky), or V*sqrt(D) from numpy.linalg.eigh for a semi-definite Sigma.
mvtpdf, mvtcdf:
    Python: distributions.py. scipy.stats.multivariate_t with mean zero, the correlation matrix and the degrees of freedom; the cdf by SciPy's randomized quasi-Monte Carlo integration, with rand's generator.
mvtrnd:
    Python: distributions.py. z*L'./sqrt(w/df): z standard normal with L the Cholesky factor of C, and w chi-square with df degrees of freedom, all from rand's generator.
randsample, datasample:
    Python: distributions.py. The choice method of rand's generator (numpy.random.RandomState.choice), with or without replacement, with the weights scaled to sum to 1. randsample(n, k) draws from 1:n; datasample takes rows of the data (a vector's elements), or slices along the dimension given.
# ---- graphics.py: figures, axes and plots --------------------------------------------------------
figure:
    Python: graphics.py and graphics_base.py. Graphics objects are Python objects that hold their properties. A command that changes one marks its figure, and the marked figures are sent to the page as a description when the command ends, or at drawnow and pause; the page draws them on a canvas. figure makes a figure with the lowest free number (or the number given) and makes it current; given a figure that exists, it makes it current and brings it forward.
gcf, gca, gco, groot:
    Python: graphics.py. The current figure (one is made when there is none), its current axes (made when it has none; the right-hand axes after yyaxis right), the object last clicked in the figure, and the root object.
clf, cla:
    Python: graphics.py. Deletes the figure's children or the axes' children and starts the colour order again; cla reset also sets the axes' properties back to their defaults.
close:
    Python: graphics.py. Runs the figure's CloseRequestFcn, whose default, closereq, deletes the figure; 'force' deletes it without asking. 'all' closes each figure whose handle is visible ('all hidden' the others too), and a name closes the figures with that Name. close(v) of a VideoWriter (animation.py) finishes its file.
hold, ishold:
    Python: graphics.py. The axes' NextPlot: 'add' keeps what the axes hold for the next plot, and 'replace' (hold off) lets the next plot clear them and their settings.
newplot:
    Python: graphics.py. The axes a plot goes into: the current axes (made when there are none), cleared and reset unless held.
subplot:
    Python: graphics.py. The axes' Position comes from the grid: the area 0.775 by 0.815 of the figure from (0.13, 0.11), divided into m rows and n columns with gaps of 0.3886 and 0.3155 of a cell (a span of cells joins them). Axes already at that place are made current, and axes that overlap it are deleted. Given axes after p, those axes are moved into the tile instead of new ones being made.
axes:
    Python: graphics.py. New axes in the current figure (or in the panel or figure given) with the properties given, made current; axes(h) makes h current.
tiledlayout, nexttile:
    Python: graphics.py. tiledlayout clears the figure and keeps the grid; nexttile puts axes in the next tile (or the one given, spanning rows and columns), the tiles filling 0.86 by 0.84 of the figure with gaps set by 'TileSpacing'. A 'flow' layout grows its grid towards a square as tiles are added and moves the axes already placed.
plot, plot3, semilogx, semilogy, loglog:
    Python: graphics.py. The arguments are split into groups of x, y (and z) and a line specification; each column of the data (or row, to match the other's length) becomes a line object holding XData, YData and ZData, coloured from the axes' ColorOrder in turn. semilogx, semilogy and loglog set XScale or YScale to 'log'. The page draws each line through its points, a NaN breaking it. plot of a graph or digraph: graphs.py (see layout).
line:
    Python: graphics.py. Line objects made in the current axes as they are, not cleared whatever hold says, from the data and properties given.
fplot, ezplot:
    Python: graphics.py. The function evaluated at 400 evenly spaced points of the interval ([-5 5] unless given): once with the whole vector, or point by point when that does not give one value for each; then plotted, with the x-limits set to the interval. Two functions give a parametric curve.
scatter, scatter3:
    Python: graphics.py. A scatter series of the points with their sizes (SizeData, in points squared) and colours (one colour, an RGB row for each point, or values mapped through the colormap); the page draws a marker at each point.
bubblechart, bubblechart3:
    Python: graphics.py. A BubbleChart series of the points with their sizes (SizeData) and colours, its faces 0.6 opaque. When the figure is drawn, each size is clipped to the axes' BubbleLim (by default the smallest and largest sizes of all their bubble charts) and its place f between the two ends gives the bubble's diameter sqrt(dmin^2 + f*(dmax^2 - dmin^2)) in points, dmin and dmax being BubbleSizeRange; so the areas grow evenly. The page draws the largest bubbles first, so that none hides a smaller one (in 3-D the farthest first).
bubblesize, bubblelim:
    Python: graphics.py. They read and set the axes' BubbleSizeRange and BubbleLim (BubbleLimMode becomes manual), as xlim does XLim.
bar, barh:
    Python: graphics.py. A bar series for each column of Y. The bars take 0.8 (or the width given) of the smallest distance between the x values; grouped bars share that width, and stacked bars pile positive and negative values separately.
histogram:
    Python: graphics.py, datafun.py and timetypes.py. A categorical array: the count of each category (its code), drawn by bar at 1, 2, ... on an axis the page labels with the categories' names. Otherwise The edges as histcounts chooses them (Scott's rule rounded to 1, 2 or 5 times a power of ten, or the number of bins, width, edges or limits given), the counts by histcounts' code, and the values normalised as asked ('count', 'probability', 'pdf', 'countdensity', 'cumcount' or 'cdf'); the page draws them as bars.
hist:
    Python: graphics.py. 10 bins of equal width between the smallest and the largest value (or the number or centres given); each value is counted in the bin with the nearest centre, by numpy.searchsorted into the midpoints and numpy.bincount, the outer bins taking everything beyond. With outputs, the counts and the centres; without, bars.
area:
    Python: graphics.py. Each column filled from the sum of the columns before it to the sum with it, starting from the base level (0 unless given).
stairs, stem:
    Python: graphics.py. Series the page draws as steps (each value held until the next x) or as stems from 0 with a marker at each value.
errorbar:
    Python: graphics.py. A series of the data with the lengths of the bars below and above each point, and left and right ones with 'horizontal' or 'both' (one length is used on both sides); the page draws each bar with caps.
pie:
    Python: graphics.py. The fractions x/sum(x) (x itself when its sum is at most 1), each slice labelled with its percentage rounded to a whole number ('< 1%' below that) unless labels are given, the colours spread evenly over the colormap; the axes are hidden and given equal scales.
polarplot, polar:
    Python: graphics.py. A line of the angles and radii in polar axes, which the page draws with rings and spokes, each point at r*cos(theta), r*sin(theta).
polaraxes:
    Python: graphics.py. Axes made as axes makes them and marked polar: the page draws them as a circle with rings at round radii and spokes every 30 degrees. Their class is PolarAxes and their Type 'polaraxes'.
polarscatter:
    Python: graphics.py. scatter's series in axes marked polar; the page puts each marker at r*cos(theta), r*sin(theta), scaled so that the outer ring is the round radius just past the largest.
polarbubblechart:
    Python: graphics.py. bubblechart's series in axes marked polar, placed as polarscatter places its markers.
quiver, quiver3:
    Python: graphics.py. A quiver series of the arrows (quiver3's with ZData and WData), scaled so that the longest, sqrt(u^2+v^2+w^2), is 0.9 (or the scale given) of the grid spacing, sqrt(dx*dy) on a grid; a scale of 0 draws them as they are. The page projects each arrow's ends and draws its two barbs in screen space, MaxHeadSize of its drawn length.
contour, contourf, contour3, contourc:
    Python: graphics.py. Each level's lines by marching squares in Python: each grid cell is classed by which of its corners are at or above the level, the crossings on its edges are placed by linear interpolation, saddle cells are split by the mean of their corners, and the segments are joined into lines. Unless given, the levels are the round tick values inside the data's range (1, 2 or 5 times a power of ten, at most 11), or n evenly spaced ones. The contour matrix holds each line as a column [level; number of points] followed by its points. contourf's bands are filled by the page, each pixel coloured by the band of the value interpolated from the grid.
clabel:
    Python: graphics.py. Sets the contour's ShowText, and the page writes the levels on its lines.
surf, mesh, surfc, meshc, meshz, waterfall, surface:
    Python: graphics.py. A surface object of X, Y, Z and C (C is Z unless given; X and Y the indices or the vectors given, through meshgrid). The page draws 3-D axes as an orthographic view from View: the back walls with their grid first, then every face and line sorted from far to near (the painter's algorithm), each face coloured through the colormap and the colour limits. mesh, meshz and waterfall draw white faces with coloured edges; surfc and meshc add contour lines at the bottom of the axes.
surfl:
    Python: graphics.py. surf with a light: the page shades each face's colour by 0.35 + 0.65*abs(dot(n, L)), with n the face's normal and L the direction of the light.
pcolor:
    Python: graphics.py. A surface lying flat at z = 0, seen from above and coloured by C.
image, imagesc, imshow:
    Python: graphics.py. An image object of C. image takes C's values as rows of the colormap (or as RGB when C has three pages); imagesc scales them between the colour limits. The axes run downwards (YDir 'reverse') and are seen from above. imshow keeps the pixels square, hides the axes, and shows a matrix in gray: uint8 over 0 to 255, logical and double over 0 to 1, or over the range given.
fill, fill3, patch:
    Python: graphics.py. Patch objects: the polygon of each column of X and Y (and Z), filled with one colour or coloured from C per face ('flat') or per vertex ('interp'). fill clears the axes unless held, patch adds to them, and patch('Faces', F, 'Vertices', V) takes the faces and vertices as given.
title, subtitle, xlabel, ylabel, zlabel:
    Python: graphics.py. Sets the String and the properties given of the axes' title, subtitle or label, a text object the axes keep.
sgtitle, suptitle:
    Python: graphics.py. A title for the whole figure, above its axes.
legend:
    Python: graphics.py. A legend object listing the plotted objects (or those given) under their DisplayName: the names given, in turn, or data1, data2 and so on; the page draws each entry's line, marker or patch beside its name.
colorbar:
    Python: graphics.py. A colorbar object beside the axes ('eastoutside' unless given), which the page draws as the colormap over the axes' colour limits.
colormap:
    Python: graphics.py and colormaps.py. Sets the figure's (or the axes') Colormap, an m-by-3 array of RGB values: a named map of 256 rows unless m is given, or the array given.
parula, viridis, turbo, jet, gray, hot, cool, spring, summer, autumn, winter, bone, copper, pink, hsv, lines, colorcube, prism, flag, white:
    Python: colormaps.py. m-by-3 arrays of RGB values, 256 rows unless m is given. gray, cool, spring, summer, autumn, winter and copper are their usual formulas in r = linspace(0, 1, m); hot ramps red, then green, then blue, each over fix(3m/8) rows, and the rest of blue over what is left; bone is (7*gray + hot reversed)/8 and pink sqrt((2*gray + hot)/3); jet places a ramp up, a plateau and a ramp down (a quarter of the map each) in blue, then green, then red, shifted by a quarter; hsv steps round the hue circle by Python's colorsys.hsv_to_rgb; lines, prism and flag repeat their colours; colorcube takes the points of an RGB grid. parula, viridis and turbo interpolate linearly between anchor colours (parula's are this page's own blue-to-yellow ramp).
caxis, clim:
    Python: graphics.py. The axes' CLim, the values mapped to the colormap's ends; until it is set, the range of the colour data the page draws ('auto').
shading:
    Python: graphics.py. Sets the surfaces' and patches' FaceColor and EdgeColor: 'flat' (one colour for each face, no edges), 'interp' (colours interpolated across each face, no edges) or 'faceted' (flat with black edges).
view:
    Python: graphics.py. The axes' View, [azimuth elevation] in degrees: 2 is [0 90] and 3 is [-37.5 30], and a direction [x y z] gives atan2(x, -y) and the elevation of the vector.
camzoom, camva:
    Python: graphics.py. The axes' CameraViewAngle: camzoom(f) makes the tangent of half the angle f times smaller, which the page draws as that much larger, cutting what then falls outside the axes.
axis:
    Python: graphics.py and glayout.py. Sets the limits, or: 'equal' (DataAspectRatio [1 1 1]), 'image' (equal and tight), 'square' (a square plot box), 'normal', 'tight' (the limits of the data), 'padded' (5% beyond them) and the like. With no arguments, the limits as they are drawn: automatic limits round out to the ticks around the data.
xlim, ylim, zlim:
    Python: graphics.py and glayout.py. Sets XLim (YLim, ZLim) and its mode to 'manual', or the mode itself; without arguments, the limits as drawn. Automatic limits are worked out on this side as the page works them out: the data's range rounded out to the ticks around it, the ticks 1, 2 or 5 times a power of ten, about one per 30 pixels and at most eleven.
xticks, yticks, zticks, xticklabels, yticklabels, zticklabels:
    Python: graphics.py and glayout.py. The axes' tick positions and labels: set (the mode then 'manual'), or the automatic ones as drawn.
xtickangle, ytickangle:
    Python: graphics.py. Sets XTickLabelRotation or YTickLabelRotation, in degrees, which the page turns the labels by.
grid, box:
    Python: graphics.py. Turns the axes' XGrid, YGrid and ZGrid (or Box) on, off or over; grid minor turns the minor grid.
text:
    Python: graphics.py. A text object at each position given, in the axes' data units (or the Units given); the page writes it with its font, alignment and rotation, reading a little TeX: ^{} and _{}, \bf and \it, and Greek letters and symbols by their names.
annotation:
    Python: graphics.py and graphics_base.py. An object of its kind (lineshape, arrowshape, doubleendarrowshape, textarrowshape, rectangleshape, ellipseshape or textboxshape) in the figure, holding its properties: for the line kinds the ends X and Y, kept in step with Position = [x1 y1 x2-x1 y2-y1]. The page draws it over the axes, in the figure's normalised units: the line, then each head as a filled outline (a triangle notched at the back for 'vback1' to 'vback3', curved for 'cback1' to 'cback3', a plain triangle, a diamond, a rectangle or an ellipse), HeadLength long and HeadWidth wide in points, the line stopping inside the head. A text box is a rectangle with its text set inside by Margin, sized to the text with FitBoxToText; a text arrow's text sits at the tail, on the side away from the head.
yyaxis:
    Python: graphics.py. A second, transparent axes at the same place, its y-axis on the right and its colour the second of the color order; yyaxis left and right choose which one plots go into.
daspect, pbaspect:
    Python: graphics.py. The axes' DataAspectRatio and PlotBoxAspectRatio, which the page keeps when it fits the plot box into the axes' position.
light, camlight:
    Python: graphics.py. A light object in the axes; surfaces that were not lit get gouraud lighting, and the page shades their faces as surfl describes.
lighting:
    Python: graphics.py. Sets FaceLighting on the axes' surfaces and patches ('phong' is taken as 'gouraud'); 'none' turns the shading off.
material:
    Python: graphics.py. Accepted and ignored: the shading has no specular part.
rotate3d, zoom, pan, datacursormode, brush:
    Python: graphics.py. Accepted and ignored: the figure's toolbar and the mouse zoom, pan, rotate and show data tips.
linkaxes, linkprop, alpha, hidden, whitebg, refresh, shg:
    Python: graphics.py. Accepted and ignored.
colororder:
    Python: graphics.py. Sets the ColorOrder of the figure's axes, the colours that new lines and series take in turn, or returns it.
set, get:
    Python: graphics.py and graphics_base.py. Each object keeps its properties in a Python dictionary. set stores each value there, colours turned into RGB triples and 'on' and 'off' into true and false (other words for those are refused), and get reads it back; some, such as automatic limits, are worked out when read. Property names are matched without regard to case, a unique beginning of one too, and get(h) lists them all.
ishandle, isgraphics, ishghandle, isvalid:
    Python: graphics.py. Whether each handle (or handle number) is an object that has not been deleted.
findobj, findall:
    Python: graphics.py. The given objects (the root unless given) and those under them, tested against property-value pairs, -regexp (Python's re.search), -property and -function, joined left to right by -and, -or and -xor with -not turning the next; -depth or flat limits how far down. findobj passes over objects whose HandleVisibility is off (callback, except while a callback runs); findall does not.
allchild, ancestor:
    Python: graphics.py. The object's children, hidden handles too; the first object of the type named, going up through the parents.
copyobj:
    Python: graphics.py. Each object is copied by Python's copy.copy and given an id (and handle number) of its own, its properties' arrays copied; its children, and the title and labels an axes keeps, are copied the same way into the copy. Then the references among the copies, such as a legend's axes and lines or an axes' legend, are pointed at the copies.
gobjects:
    Python: graphics.py. An array of graphics placeholders of the size given, to be filled with handles.
drawnow:
    Python: graphics.py. Sends the changed figures to the page at once, then runs the callbacks of the clicks and keys that have come in ('nocallbacks' leaves them).
peaks:
    Python: graphics.py. 3*(1 - x).^2.*exp(-x.^2 - (y + 1).^2) - 10*(x/5 - x.^3 - y.^5).*exp(-x.^2 - y.^2) - 1/3*exp(-(x + 1).^2 - y.^2) on a 49-by-49 grid over [-3, 3] (or the size or points given); without outputs, its surface.
sphere, ellipsoid, cylinder:
    Python: graphics.py. Coordinates by NumPy over n + 1 angles (n = 20 unless given): the sphere's cos(phi).*cos(theta), cos(phi).*sin(theta), sin(phi), stretched and moved for an ellipsoid; the cylinder's circles of the radii given at heights evenly spaced from 0 to 1. Without outputs, the surface with equal axes.
fsurf, ezsurf, fmesh, ezmesh, fcontour, ezcontour:
    Python: graphics.py. The function evaluated on a grid of 35 by 35 points (60 by 60 for contours) over the interval ([-5 5] in each direction unless given), with whole arrays, or point by point when that fails; then drawn as surf or contour draws it.
saveas, print, exportgraphics:
    Python: graphics.py, with the page's pylab-figure.js and pylab-export.js. The kind comes from the file's extension, or else from print's -d device or saveas's format. The page draws the figure on a canvas, at twice its size on screen unless a resolution is given, for .png and .jpg (the canvas's own encoders) and for .bmp and .tif (its pixels written uncompressed). For .svg, .pdf and .eps the figure is drawn by the same code into a recorder instead: an object with the canvas's drawing calls that keeps the paths, text, pictures and gradients drawn instead of painting pixels. They are written as SVG, as a PDF page (text in the standard Helvetica, Courier and Symbol fonts, images with their transparency, gradients as axial shadings) or as Encapsulated PostScript of LanguageLevel 3 (translucent colours mixed with white). A .fig name writes a figure file; print -dmeta with no file copies the picture to the clipboard.
openfig, hgload, open:
    Python: graphics.py and figfile.py. A figure file is a MAT-file whose variable hgS_070000 holds the figure as a tree of structs, one for each object with its type, properties and children; it is read by the MAT-file reader and the objects are made again from the tree. open also loads a MAT-file and sends other files to the Editor.
savefig, hgsave:
    Python: graphics.py and figfile.py. The objects written as that tree of structs into a MAT-file by SciPy's scipy.io.savemat; callbacks given as function handles are left out (text callbacks are kept), and so are annotations, each with a warning.
getframe:
    Python: graphics.py. The page draws the figure on a canvas at its size on screen and sends back the pixels of the figure, of an axes' box or of the rectangle given, as RGB over white; they become cdata, a uint8 array of rows by columns by 3.
frame2im, im2frame:
    Python: graphics.py. The frame's cdata (and colormap); or a struct of cdata and colormap made from a picture, doubles from 0 to 1 turned into uint8 by round(255*x).
movie:
    Python: graphics.py. An image object in the axes whose CData is set to each frame in turn; the figure is drawn and the engine waits 1/fps seconds between frames, as pause does (callbacks run, Ctrl+C stops it).
ginput:
    Python: graphics.py. The page takes the next n clicks in the current axes (or clicks until Enter) and gives back their data coordinates and the buttons pressed.
waitforbuttonpress:
    Python: graphics.py. Waits for a key in the Command Window, as pause does.
# ---- uifun.py: user interfaces --------------------------------------------------------------------
uicontrol, uipanel, uibuttongroup, uitable, uitabgroup, uitab:
    Python: uifun.py and uiobjects.py. Objects with properties, like the other graphics objects, in the figure (or the panel, group or tab given). The page builds each as an HTML element over the figure's canvas (a button, a check box, a text field, a slider, a list, a table, a tab strip), placed by its Position in its Units. What people do with it comes back to the engine, which sets Value, String and the like at once and queues the callback; the callbacks run when the engine is idle, or at drawnow, pause, uiwait and waitfor in a running program.
uimenu, uicontextmenu, uitoolbar, uipushtool, uitoggletool:
    Python: uifun.py and uiobjects.py. Menus in the figure's menu bar (or under another menu), a menu that opens at a right-click on the objects whose UIContextMenu it is, and toolbars with push and toggle tools; the page builds them as HTML and queues their callbacks as for controls.
gcbo, gcbf:
    Python: uifun.py and uievents.py. The object whose callback is running and its figure, from the stack of callbacks the engine keeps as it runs them; [] outside a callback.
closereq:
    Python: uifun.py. Deletes the figure whose callback is running (or the current figure): the default CloseRequestFcn.
uiwait, uiresume:
    Python: uifun.py and uievents.py. uiwait waits in steps of 0.02 s (asyncio.sleep), running the callbacks of what people do meanwhile, until uiresume marks the figure, the figure is deleted, or the timeout has passed.
waitfor:
    Python: uifun.py and uievents.py. Waits as uiwait does, running callbacks meanwhile, until the object is deleted, or until the property changes (or takes the value given), compared with isequal.
setappdata, getappdata, isappdata, rmappdata:
    Python: uifun.py. A Python dictionary kept with the object, from names to values.
guidata:
    Python: uifun.py. The value kept in the figure's application data under the name UsedByGUIData_m, for the figure of the object given.
inspect:
    Python: uifun.py and inspector.py. Asks the page to open its property editor (pylab-inspector.js) beside the object's figure. The page then asks inspector.py for the object's properties: each property's value as getprop gives it, sorted into groups (the common ones for the object's kind first) and given a kind of field: colour, on/off, a list of choices, number, numbers, lines of text, colormap, callback, a link to another object, or read-only. A change typed there is read as a literal (numbers, a matrix in brackets, text, a colour name, hex code or [r g b]; a callback starting with @ is made by the code str2func uses), set with setprop as set does, and the figure is redrawn.
plotedit:
    Python: uifun.py. Asks the page to switch the figure's edit mode, the toolbar's arrow tool: a click then picks the topmost part under it (a legend or colorbar, a text, an annotation, a plotted object, its axes or the figure) for the property editor, and outlines it, without telling the program.
movegui:
    Python: uifun.py. Asks the page to move the figure's window to the place named (onscreen unless given) on the desktop.
uistack:
    Python: uifun.py. Moves the object up, down, to the top or to the bottom of its parent's list of children, the order in which the page draws and stacks them.
helpwin, doc:
    Python: uifun.py. Opens the name in the page's Help browser.
msgbox, errordlg, warndlg, helpdlg:
    Python: uifun.py. A figure made as a dialog, centred and without menus: the message's lines broken at spaces to at most 75 characters, an icon drawn in Python as a 32-by-32 picture (or the one given), and an OK button that deletes it. It returns at once, without waiting for the OK; uiwait waits for it. With 'modal' the figure is modal, as dialog describes.
dialog:
    Python: uifun.py. An empty figure for a dialog of the program's own controls, with WindowStyle 'modal'. While a modal figure is shown, the page lays a veil over everything else, which takes the clicks, keeps the keys typed elsewhere from arriving (Ctrl+C still stops a program) and keeps the focus in the figure.
waitbar:
    Python: uifun.py. A small dialog figure holding axes with a patch, the bar, whose width is x times 100 of the axes' 0 to 100, and the message as the axes' title; waitbar(x, h) moves the bar and changes the message.
questdlg, inputdlg, listdlg, menu, uisetcolor:
    Python: uifun.py. The page shows the dialog as HTML and the engine waits for the answer: the button pressed, the texts typed, the items chosen, the colour; '' (or {} or 0) when it is cancelled.
uigetfile, uiputfile, uigetdir:
    Python: uifun.py. The page shows a file chooser over the engine's own file system (the files the Current Folder shows, not the computer's), starting in the current folder or the folder given and filtered by the patterns given; the name and the folder chosen, or 0 when it is cancelled.
printdlg, printpreview:
    Python: uifun.py. The page prints the figure through the browser's print dialog.
timer:
    Python: uifun.py and uievents.py. A handle object holding the timer's properties. start runs StartFcn and asks the page's clock to tick after StartDelay seconds and then every Period seconds as ExecutionMode says; each tick queues TimerFcn, which runs as other callbacks do, so a busy program delays it. stop runs StopFcn.
start, stop, wait:
    Python: uifun.py and uievents.py. Start or stop the timers (see timer), or wait, running callbacks meanwhile, until they have stopped.
timerfind, timerfindall:
    Python: uifun.py. The timers that have not been deleted (timerfind only those whose ObjectVisibility is on) whose properties have the values given, compared with isequal.
sound, soundsc:
    Python: uifun.py. The samples (a column for each of one or two channels) sent to the page as 32-bit floats, which the browser's audio plays at once at the rate given (8192 Hz unless given); sound clips them to [-1, 1], soundsc first scales the data's range (or the range given) onto it.
beep:
    Python: uifun.py. A tone of 880 Hz lasting 0.12 s, played as sound plays it, unless beep off was given.
# ---- validators.py: arguments ------------------------------------------------------------------
mustBePositive, mustBeNonnegative, mustBeNegative, mustBeNonpositive, mustBeNonzero, mustBeInteger, mustBeFinite, mustBeNonNan, mustBeReal:
    Python: validators.py. The values as a NumPy array (numeric or logical, or the error saying it must be), then one test on all of them: > 0, >= 0, < 0, <= 0, != 0, whole and finite, numpy.isfinite, not numpy.isnan, no imaginary part. NaN fails the comparisons. The error's identifier is MATLAB:validators: and the function's name.
mustBeGreaterThan, mustBeGreaterThanOrEqual, mustBeLessThan, mustBeLessThanOrEqual, mustBeInRange:
    Python: validators.py. The values compared with the bound (or bounds) by NumPy, NaN failing; mustBeInRange includes both bounds unless 'exclusive', 'exclude-lower' or 'exclude-upper'.
mustBeNumeric, mustBeNumericOrLogical, mustBeFloat, mustBeNonempty, mustBeNonsparse, mustBeScalarOrEmpty, mustBeVector:
    Python: validators.py. The value's class or size: numeric, numeric or logical, single or double, at least one element, at most one, a row or a column (or any empty with 'allow-all-empties'); mustBeNonsparse fails for a sparse matrix.
mustBeMember:
    Python: validators.py. Numbers by numpy.isin; text compared as text, every element of A among those of S.
mustBeText, mustBeTextScalar, mustBeNonzeroLengthText, mustBeValidVariableName:
    Python: validators.py. The value's class and shape: a character row (or matrix), a string array, or a cell of character vectors; one text for the scalar form; no empty text; each text a valid name by isvarname.
mustBeA, mustBeUnderlyingType:
    Python: validators.py. The value's class (or, for an object, its superclasses) against the names given; mustBeA also takes 'numeric', 'float' and 'integer' for their groups.
mustBeNonmissing:
    Python: validators.py. No NaN in numbers and no missing string.
mustBeFile, mustBeFolder:
    Python: validators.py. Each name, from the current folder, tested by Python's os.path.isfile or os.path.isdir.
nargchk:
    Python: validators.py. 'Not enough input arguments.' when n < low, 'Too many input arguments.' when n > high, else ''; with 'struct', a struct of message and identifier (0-by-1 when n is within).
namelengthmax:
    Python: elmat.py. 63.
inputParser, addRequired, addOptional, addParameter, addParamValue, parse:
    Python: validators.py. A handle object holding the inputs in the order added: required, optional (with defaults) and name-value parameters (with defaults and a PartialMatchPriority). parse takes the required inputs in turn, then the optional ones, stopping at text that names a parameter (or that an optional input's check refuses), then name-value pairs, a struct standing for its fields' pairs when StructExpand is on. A name matches a parameter exactly or, with PartialMatching, by a prefix that picks one (case ignored unless CaseSensitive). Each value is given to its validation function, which passes by returning true (or nothing) and fails by returning false or giving an error; the message names the input and the function. Unknown names go to Unmatched when KeepUnmatched is on and are an error otherwise. Results and Parameters list the names in alphabetical order; UsingDefaults those not given. The methods are also called as p.addRequired(...) and p.parse(...).
# ---- datatools.py: missing data, outliers, smoothing, groups ----------------------------------------
missing:
    Python: missingdata.py. A value object of NaN placeholders: concatenation, assignment and arithmetic turn it into the missing value of the other value (NaN, a missing string, NaT, a duration of NaN, an undefined category), and string, double, single, datetime, duration, calendarDuration and categorical convert it.
fillmissing:
    Python: datatools.py and missingdata.py. Datetimes and durations are filled as their seconds; 'previous', 'next' and 'nearest' (all classes) fill the elements' positions and the elements follow; 'constant' sets the value given, made of the array's class. A table is filled variable by variable. Each vector along the dimension on its own: the missing entries (NaN; empty text in a cell; missing strings; blank characters) are filled from the others by their positions: 'previous', 'next' and 'nearest' (a tie to the earlier) copy a known value; 'linear', 'spline' (not-a-knot), 'pchip' and 'makima' interpolate through the known points with SciPy's interp1d, CubicSpline, PchipInterpolator and Akima1DInterpolator; 'movmean' and 'movmedian' take numpy.nanmean or numpy.nanmedian of the window around each missing entry; 'constant' puts a value (or one per vector). The entries before the first known value and after the last are filled by EndValues: extrapolated by the method ('extrap', the default), by 'previous', 'next' or 'nearest', by a value, or left ('none'). MaxGap leaves gaps wider than it (from the known value before to the one after). The second output marks what was filled.
rmmissing:
    Python: datatools.py and missingdata.py. A table loses the rows whose missing elements (in its variables, or in DataVariables) number MinNumMissing (1) or more; other classes go through their elements' positions. A vector without its missing entries; a matrix without the rows (or columns, dim 2) with at least MinNumMissing (1) missing entries; the second output marks what was removed.
standardizeMissing:
    Python: datatools.py and missingdata.py. A categorical array's indicated categories become undefined (code 0); datetimes and durations equal to an indicator become NaT or NaN; a table's variables each take the indicators of their kind. Otherwise numpy.isin of the numbers against the indicators, those set to NaN (integers have no missing value and are refused); in text, matching elements made empty or missing.
isoutlier:
    Python: datatools.py. Each vector along the dimension, NaN left out: 'median' takes the median and the median absolute deviation times 1.4826 (so that for normal data it estimates the standard deviation), outliers being more than 3 of those from the median; 'mean' the mean and the standard deviation (n - 1); 'quartiles' the quartiles (the language's quantiles, values at (i - 0.5)/n) and 1.5 interquartile ranges beyond them; 'grubbs' removes the farthest value from the mean while Grubbs's statistic passes its critical value at alpha 0.05 (from scipy.stats.t); 'gesd' runs the generalized extreme studentized deviate test for up to MaxNumOutliers (a tenth of the values, rounded up) and keeps the largest number that passed; 'movmedian' and 'movmean' do the median or mean test in each window. ThresholdFactor replaces the 3 (the 1.5, or alpha). L, U and C are the bounds and the centre.
filloutliers:
    Python: datatools.py. The outliers isoutlier finds replaced: by the centre, clipped to the bounds, by a number, or by fillmissing's methods with the outliers as the gaps (NaN in the data is neither filled nor used).
smoothdata:
    Python: datatools.py. Each vector along the dimension: 'movmean' and 'movmedian' over the window (NaN left out by numpy.nanmean and numpy.nanmedian unless 'includenan'); 'gaussian' weights the window by a normal curve whose standard deviation is a fifth of the window; 'lowess' and 'loess' fit a line or a parabola to each window by least squares (numpy.linalg.lstsq) with tricube weights by distance, the r forms reweighting by bisquare weights of the residuals five times; 'sgolay' is scipy.signal.savgol_filter (Degree 2, its ends fitted). Without a window, 4 or a tenth of the length, whichever is larger (PyLAB's choice); the second output is the window.
findgroups:
    Python: datatools.py. The distinct values (or combinations of values across the inputs) sorted, numbered from 1, and each element given its number; NaN, empty text and missing strings get NaN. The further outputs are the values of each group.
splitapply:
    Python: datatools.py. For each group number 1..max(G), the rows (or elements of vectors) of each data input in that group given to the function together, its outputs (one row each) stacked by vertical concatenation; rows with group NaN are left out, and a group number with no rows is an error.
histcounts2:
    Python: datatools.py. Edges for each coordinate as histcounts chooses them (round widths, Scott's rule) unless given, each pair counted into its cell of the grid with numpy.add.at (bins [e(k), e(k+1)), the last closed); pairs with NaN or outside are in no bin (bin 0). Normalization as histcounts, with the cells' areas.
rms:
    Python: datafun.py. sqrt(mean(abs(x).^2)) by NumPy along the dimension (a vector of them, or 'all'), numpy.nanmean with 'omitnan'; single stays single.
# ---- arrays, cells, coordinates, text, JSON --------------------------------------------------------
bsxfun:
    Python: elmat.py. Both arrays expanded along their dimensions of size 1 to the size of the other (numpy.broadcast_to), the function then called once with the two.
repelem:
    Python: elmat.py. numpy.repeat of the vector's elements, or along each dimension of an array in turn, by a count or one count per element of that dimension; characters, cells and strings too.
mat2cell:
    Python: cellfun.py. The array sliced into the blocks the sizes give (their sums must be the array's sizes; a dimension not given is one block), each block a cell.
celldisp:
    Python: cellfun.py. Each element shown as display would show it, named C{i} (C{i,j} for a matrix), cells inside cells taken apart in turn; the name is the variable in the caller holding that very cell, or 'ans'.
swapbytes:
    Python: elmat.py. NumPy's byteswap of the array, its class kept.
spfun:
    Python: sparse.py. The function called once on the column of stored values (in column order), its results put back in their places in a sparse matrix.
cart2pol, pol2cart, cart2sph, sph2cart:
    Python: elfun.py. numpy.arctan2 and numpy.hypot (theta = atan2(y, x), rho = hypot(x, y); elevation = atan2(z, hypot(x, y)), r = hypot(hypot(x, y), z)), or cos and sin (x = rho cos(theta), y = rho sin(theta); x = r cos(elevation) cos(azimuth) and so on), the inputs broadcast to one size; single in gives single out.
replaceBetween, eraseBetween:
    Python: strfun.py. For text markers, each start marker found by str.find with the next end marker after it, the text between replaced (the markers too with 'Boundaries', 'inclusive'); for positions, the characters from the start to the end position, both included.
matlab.lang.makeUniqueStrings:
    Python: strfun.py. The names in order: one that repeats an earlier one, or is in the list to avoid, gets the smallest _k that makes it new (cut so that the whole stays within maxLength); the first of each is kept. A logical or index second input picks the elements that may change instead.
jsondecode:
    Python: iofun.py. Python's json.loads, then: an object becomes a struct (names made valid by matlab.lang.makeValidName); an array of numbers a column (null as NaN), of booleans a logical column, of arrays of numbers alike a matrix (each inner array a row), of objects with the same fields a struct array; any other array a cell column; null alone []; text a character vector.
jsonencode:
    Python: iofun.py. The value as Python data, then json.dumps: numbers (whole ones without a point, singles by their own shortest digits, Inf and NaN as null unless 'ConvertInfAndNaN' is false), logical as true and false, a character row as a string (a matrix as a list of its rows), vectors as lists and matrices as lists of rows, cells as lists, a struct as an object (an array of them as a list), a containers.Map as an object; 'PrettyPrint' indents by two spaces.
# ---- matfun.py: structure, iterative solvers, updates -------------------------------------------------
issymmetric, ishermitian:
    Python: matfun.py. A compared with its transpose (conjugate transpose for ishermitian), or with minus it for 'skew', element by element (for a sparse matrix, the difference of SciPy's matrices has no stored values); with a tolerance, the largest row sum of abs(A - A.') against tol times that of A (the infinity norms). A matrix that is not square gives false.
istril, istriu, isbanded, bandwidth:
    Python: matfun.py. numpy.nonzero gives the positions of the nonzeros (SciPy's COO form for a sparse matrix); the lower bandwidth is the largest i - j among them, the upper the largest j - i (0 for none). Of a model: control.py, the -3 dB crossing refined by scipy.optimize.brentq.
pcg, bicg, bicgstab, cgs, gmres, minres, qmr, tfqmr:
    Python: matfun.py. SciPy's scipy.sparse.linalg cg, bicg, bicgstab, cgs, gmres, minres, qmr and tfqmr with rtol the tolerance (1e-6 unless given) and no absolute tolerance, maxit min(n, 20) unless given (gmres: restart n, at most min(n/restart, 10) restarts), x0 zeros unless given. A sparse matrix is passed to SciPy as it is; a function handle is wrapped as a LinearOperator (bicg and qmr call it with 'notransp' and 'transp'); the preconditioner M = M1*M2 becomes the operator that solves M*y = r, each factor factored once (scipy.sparse.linalg.splu for a sparse one, scipy.linalg.lu_factor for a full one) or called (a handle). relres is norm(b - A*x)/norm(b) computed after the solve, flag 0 when it meets the tolerance, 1 when the iterations ran out, 4 when SciPy reports a breakdown; resvec holds norm(b - A*x) at the start and after each iteration (gmres: SciPy's residual estimate at each inner step).
lsqr:
    Python: matfun.py. scipy.sparse.linalg.lsqr with atol and btol the tolerance and iter_lim maxit (min(m, n, 20) unless given), a sparse matrix passed as it is; a preconditioner P = M1*M2 by lsqr on the operator A*inv(P) (its factors factored once) and x = P\y; flag 0 when LSQR stops on its tolerances, 1 on its iteration limit.
cholupdate:
    Python: matfun.py. scipy.linalg.cholesky of R'*R + x*x' (or - x*x'); a matrix that is no longer positive definite gives p = 1 and R back unchanged (an error with one output).
qrupdate, qrinsert, qrdelete:
    Python: matfun.py. scipy.linalg.qr_update (with the conjugate of v, so that Q*R + u*v' is factored), qr_insert and qr_delete (the column or row j counted from 1), which update the factors by Givens rotations rather than factoring again.
qz:
    Python: matfun.py. scipy.linalg.qz with output 'complex' (the default) or 'real'; SciPy's A = Q*AA*Z' is turned around so that Q*A*Z = AA (Q is SciPy's Q'). V and W are scipy.linalg.eig's right and left generalized eigenvectors, each column scaled to unit norm.
ordschur:
    Python: matfun.py. LAPACK's trsen (scipy.linalg.lapack.dtrsen or ztrsen, without condition numbers), which moves the selected eigenvalues to the top by exchanging diagonal blocks, both of a real 2-by-2 block together; keys are taken as clusters, moved to the top from the smallest key up so that larger keys end first.
ordqz:
    Python: matfun.py. LAPACK's tgsen (scipy.linalg.lapack.dtgsen or ztgsen, ijob 0, without condition numbers), which moves the selected eigenvalues of the pencil to the top by exchanging diagonal blocks, both of a real 2-by-2 block together. LAPACK's Q is the transpose of the language's (A = Q*AA*Z'), so Q goes in transposed and comes out transposed back. Keywords pick the eigenvalues AA(i,i)/BB(i,i) (a 2-by-2 block's pair by scipy.linalg.eigvals); keys are taken as clusters, moved to the top from the smallest key up.
rsf2csf:
    Python: matfun.py. scipy.linalg.rsf2csf: each real 2-by-2 block of T is made triangular by a complex Givens rotation, applied to U as well.
gsvd:
    Python: matfun.py. The QR factorization of [A; B] (numpy.linalg.qr, the economy size), Q's columns completed to a square unitary matrix, and its CS decomposition (scipy.linalg.cossin) split after A's rows: Q's top part is U*C*Z' and its bottom part V*S*Z', so A = U*C*(Z'*R) and B = V*S*(Z'*R), X = R'*Z. The pairs (c, s) are put in order of c/s increasing, C's nonzeros on its diagonal max(0, q - m) to the right and S's on its main diagonal, U's and V's columns following; any sign goes into U's or V's column so that C and S are not negative.
gallery:
    Python: gallerymat.py. Each matrix from its defining formula in NumPy (Higham's definitions): Cauchy 1./(x + y'), Chebyshev-Vandermonde by the three-term recurrence, Fiedler abs(c - c'), Lehmer min(i,j)/max(i,j), the Pascal-based binomial matrix L*diag((-2).^(0:n-1))*L(end:-1:1, end:-1:1), the involutory matrix from the Hilbert matrix with its rows scaled, Poisson and Neumann by scipy.sparse.kron of tridiagonal matrices, and so on. randsvd multiplies the chosen singular values by random orthogonal matrices (QR of normal matrices, signs fixed); randhess multiplies plane rotations; the data sets use a numpy.random.RandomState of their own, seeded by j. chebspec from the Chebyshev points' formula, c_i/c_j (-1)^(i+j)/(x_i - x_j) off the diagonal; wathen assembles the 8-node serendipity element's mass matrix (an 8-by-8 integer matrix over 45) times each element's density with scipy.sparse.
ordeig:
    Python: matfun.py. The diagonal of T read in order, each real 2-by-2 block giving its pair of eigenvalues (numpy.linalg.eigvals, the one with positive imaginary part first); for AA and BB the ratios of their diagonals.
polyeig:
    Python: matfun.py. The companion pencil of size n*p, [0 I ...; -A0 -A1 ... -A(p-1)] against diag(I, ..., Ap), solved by scipy.linalg.eig; the eigenvectors are the first n rows of the pencil's, scaled to unit norm. s is (sum |e|^k norm(Ak)) norm(x) norm(y)/(|e| |y'*P'(e)*x|), y the left eigenvector.
# ---- geometry.py: triangulations, searching, interpolation objects -------------------------------------
delaunay:
    Python: geometry.py. scipy.spatial.Delaunay (Qhull) of the points, its simplices counted from 1.
convhull:
    Python: geometry.py. scipy.spatial.ConvexHull (Qhull): in 2-D its vertices, counterclockwise, the first repeated at the end, points on straight edges dropped (kept and put in their places with 'Simplify', false), and its area; in 3-D its triangles and volume.
voronoi, voronoin:
    Python: geometry.py. scipy.spatial.Voronoi (Qhull). voronoin gives its vertices after a first row of Inf, and each point's region with Qhull's -1 (the point at infinity) as 1. voronoi gives the ridges as edges, an unbounded ridge drawn from its vertex outward along the perpendicular bisector of its two points to twice the spread of the points; with no outputs it plots the points and the edges.
tsearchn:
    Python: geometry.py. For each simplex, the barycentric coordinates of the points (by the inverse of the matrix of its vertices with a row of ones); the first simplex where all are 0 or more (within 1e-12) holds the point; NaN for none.
dsearchn:
    Python: geometry.py. scipy.spatial.cKDTree's query: the nearest point and the distance; with T and outval, points that no Delaunay triangle holds (scipy.spatial.Delaunay.find_simplex) get outval.
rectint:
    Python: geometry.py. For each pair of rectangles, the overlap of their x ranges times that of their y ranges, 0 where either is empty.
interp3:
    Python: geometry.py. interpn with the axes swapped: in meshgrid's layout y runs down the rows and x across, so interp3(X, Y, Z, V, xq, yq, zq) is interpn(y, x, z, V, yq, xq, zq); full grids are reduced to their vectors.
griddedInterpolant:
    Python: geometry.py. A handle object holding the grid vectors and the values; F(...) evaluates inside the grid by interp1 (one dimension) or interpn with the method, so the values are those of those functions, and outside it by the extrapolation method: interp1 with 'extrap', or scipy.interpolate.RegularGridInterpolator (linear, nearest, cubic for spline, cubic and makima, pchip) with no bounds; 'none' gives NaN. A cell of vectors evaluates on their grid (numpy.meshgrid with 'ij').
scatteredInterpolant:
    Python: geometry.py. A handle object holding the points and values. 'linear' (and 'natural', which SciPy does not have) is scipy.interpolate.LinearNDInterpolator over the Delaunay triangulation, 'nearest' NearestNDInterpolator. Outside the convex hull: 'nearest' takes the nearest point's value, 'linear' extends the plane through the hull triangle (simplex) whose centre is nearest, 'none' gives NaN. Changing Values keeps the triangulation.
triplot:
    Python: geometry.py. plot of all the triangles' edges as one line, a NaN between triangles.
trisurf, trimesh:
    Python: geometry.py. patch with Faces the triangles and Vertices [x y z], coloured by FaceVertexCData z (or c): flat faces with black edges for trisurf, white faces with coloured edges for trimesh; then view(3).
# ---- gsa.py: sensitivity analysis and sampling ---------------------------------------------------
lhsdesign:
    Python: gsa.py. Each column the ranks of uniform numbers (numpy's argsort), less a uniform jitter (or a half), over n. 'maximin' keeps the candidate with the largest least distance between points (scipy.spatial.distance.pdist), 'correlation' the one with the smallest sum of squared correlations between columns.
lhsnorm:
    Python: gsa.py. A normal sample from the Cholesky factor of Sigma (or its eigenvectors when it is only semi-definite); each column's values replaced, in the order of their ranks, by mu + sigma times the normal quantile (scipy.stats.norm.ppf) of (rank - u)/n, u uniform or a half.
sobolset, haltonset, net, scramble:
    Python: gsa.py. scipy.stats.qmc.Sobol (Joe and Kuo's direction numbers) and scipy.stats.qmc.Halton, the points from the start up to the last one asked for, then those after Skip, every Leap+1 th. Scrambling is SciPy's: a random linear matrix scramble with a digital shift for Sobol, random permutations of the digits for Halton, seeded from the generator rng sets.
src, srrc, pcc, prcc:
    Python: gsa.py. Kompartment's regression measures: the inputs and the output standardized, the inputs' correlation matrix factorized by Cholesky (scipy.linalg.cho_solve gives its inverse), SRC the solution of the normal equations and R² its product with the correlations; PCC_k = SRC_k / sqrt(SRC_k² + (1 - R²) (R⁻¹)_kk). A constant input gets NaN; all do when the inputs are collinear. The rank forms on scipy.stats.rankdata.
firstorderindex:
    Python: gsa.py. The runs sorted by the input and cut into bins of equal count; the bins' means' variance over the output's, less bins/n for the noise in the means, within 0 to 1.
easi:
    Python: gsa.py. Plischke's EASI: the outputs sorted by the input and folded into a triangle (the even places going up, the odd coming down), the power spectrum (numpy.fft.rfft) of that, and the share of its power in the first harmonics; S1c less Tissot and Prieur's bias lambda/(1 - lambda)(1 - S1), lambda = 2h/n.
deltamoment:
    Python: gsa.py. Plischke, Borgonovo and Smith's estimator, as GlobalSensitivity.jl: the input's ranks cut into classes (n^(2/(7 + tanh((1500 - n)/500))), at most 48), the output's density and its density in each class by KernelDensity.jl's kernel estimate (linear binning on 2048 points, the Gaussian in Fourier space, a quadratic B-spline, scipy.linalg.solve_banded), half the mean area between them; the bias of a bootstrap taken off. Read on the output's normal scores.
mutualinfo:
    Python: gsa.py. Histograms of equal-width bins (the square root of n a side) of the ranks, the entropies in bits and the mutual information as Hx + Hy - Hxy; the chance level the conf quantile of the same over shuffles of Y (numpy permutations).
pawn:
    Python: gsa.py. The input's quantiles at i/s cut it into s slices; in each, scipy.stats.ks_2samp between the output there and overall, as SALib.
discrepancyshares:
    Python: gsa.py. As SALib: each input's points ((rank - 1/2)/n, the output's ranks scaled onto 0 to 1), their discrepancy by scipy.stats.qmc.discrepancy, over the sum.
rsa:
    Python: gsa.py. scipy.stats.ks_2samp between each input above and at or below the threshold; the dummies uniform numbers from the generator rng sets.
morrisdesign, morrisindices:
    Python: gsa.py. Kompartment's ports of GlobalSensitivity.jl and SALib, giving the same numbers from the same draws. Walks: each starts at a random level and each step moves a random input one level, bouncing off the ends. Trajectories: a random order and direction for the inputs and a start in the lower half of the levels, each input moved by half the levels in turn; with candidates, Ruano, Ewald and Kolar's local search for the most spread-out set by SALib's distances (summed point to point, in single precision). An effect is the change in the output over the change in the moved input; MuStarConf is the normal quantile times the spread of the mean magnitude over bootstrap resamples of the input's effects.
soboldesign, sobolindices:
    Python: gsa.py. Saltelli's (2010) first-order estimator, mean(f_B (f_AB - f_A)) over the variance of A and B together, and the total estimators of Jansen (mean((f_A - f_AB)^2)/2), Sobol (2007), Homma and Saltelli (1996) and Janon (2014); pairs from B with each column of A. With blocks, the means over blocks and the normal quantile times their standard error; with one block, SALib's bootstrap: the rows of every sample resampled together, the output standardized.
efastdesign, efastindices:
    Python: gsa.py. As GlobalSensitivity.jl: the input's frequency (N - 1)/(2M) and the others' below it, each curve 1/2 + asin(sin(pi(omega s + phi)))/pi with a random phase; S1 is the power (numpy.fft.rfft) at the input's frequency and its M harmonics over the power at every frequency, ST one less the power at frequencies up to half the input's.
rbdfastdesign, rbdfastindices:
    Python: gsa.py. One path from -pi to pi taken by every input in its own random order (Fisher-Yates), mapped through asin(sin); the outputs sorted by an input's path, S1 twice the power of the first harmonics over the whole; the correction is SALib's unskew.
ffdesign, ffindices:
    Python: gsa.py. A Sylvester-Hadamard matrix of order the power of two at or above K and its negative; a main effect is the output's contrast with the input's signs over the runs, an interaction the contrast with the product of two inputs' signs.
dgsmdesign, dgsmindices:
    Python: gsa.py. Forward differences (back where a step forward would leave 0 to 1) at Latin hypercube points, mixed second differences for the pairs; the means of the derivative, its magnitude and its square, GlobalSensitivity.jl's sigma and tao, the bound nu/(pi^2 Var y), and SALib's bootstrap on nu.
radialdesign, radialindices:
    Python: gsa.py. As SALib: each base point and the point after each move; the effects the differences over the moves, numpy.nan_to_num for a move of nothing, ST the mean squared difference over twice the base points' variance, the intervals from bootstrap resamples of the base points.
shapleydesign, shapleyindices:
    Python: gsa.py. Song, Nelson and Staum's algorithm, as GlobalSensitivity.jl: for each order and step the inputs not yet learnt fixed at outer points and the others drawn given them; with a correlation matrix the draws are normal scores (Box-Muller) through scipy.stats.norm.cdf, the conditional mean and covariance from the Cholesky factor of the conditioning block. Each input's effect the mean, over the orders, of the rise in the expected conditional variance it brings, over the variance.

# ---- imagecolor.py: images and colours ----------------------------------------------------------
im2double, im2single, im2uint8, im2uint16:
    Python: imagecolor.py. Each integer class mapped linearly from its range onto 0 to 1 (int16 from -32768 to 32767), then, for an integer result, onto that class's range with numpy.round after numpy.clip; NaN becomes 0. 'indexed' adds or takes away 1 instead, and refuses indices the class cannot hold.
rgb2gray, im2gray, cmap2gray:
    Python: imagecolor.py. A matrix product of the last dimension with the weights 0.298936021293775, 0.587043074451121 and 0.114020904255103, in double on the image's own values, then rounded and clipped for the integer classes.
mat2gray:
    Python: imagecolor.py. (A - amin)/(amax - amin) with numpy.clip to 0 to 1, the limits from the finite values unless given.
rgb2hsv, hsv2rgb:
    Python: imagecolor.py. The value is the largest of R, G and B and the saturation the spread over it; the hue the sector of the largest (red, then green, then blue taking ties) plus the difference of the other two over the spread, in sixths of a turn. Back, the sector numpy.floor(6h) picks which of v, v(1-s), v(1-sf) and v(1-s(1-f)) each of R, G and B is. Integer values are scaled by their class's range first, both ways.
rgb2lightness:
    Python: imagecolor.py. sRGB's companding undone (c/12.92 up to 0.04045, ((c+0.055)/1.055)^2.4 above), the luminance Y = 0.2126729 R + 0.7151522 G + 0.0721750 B, and L* = 116 f(Y) - 16 with f the cube root above (6/29)^3 and the straight line below.
ind2rgb, ind2gray:
    Python: imagecolor.py. The indices (from 1 for double, from 0 for the integer classes) clipped to the colormap and used to index its rows (or the rows' gray levels).
gray2ind:
    Python: imagecolor.py. numpy.round of the image's values (0 to 1, clipped) times n - 1.
rgb2ind:
    Python: imagecolor.py. Minimum variance quantization is Wu's (Graphics Gems II, 1991): the colour cube in 32 slices a side, a histogram with each cell's count, sums and sum of squares accumulated so that any box's moments come from eight corners; the box of largest summed variance is cut next, on the axis and at the place where the two halves' variance falls most, until there are n boxes, whose mean colours are the colormap. Without dithering each pixel takes the nearest colour (scipy.spatial.cKDTree). Dithering is Floyd and Steinberg's error diffusion in raster order (7/16 to the right, 3/16, 5/16 and 1/16 below), the nearest colour of each corrected value read from a table of the nearest colour to the middle of each of 32 slices a side.
imsplit:
    Python: imagecolor.py. Each slice I(:,:,k), copied.

# ---- media.py: images, sound and the web --------------------------------------------------------
imread, imfinfo:
    Python: media.py. Pillow (PIL.Image.open; in the page, Pyodide loads the package the first time) reads the file; its pixels become a NumPy array by the image's mode: gray as m-by-n uint8 (16-bit as uint16), colour as m-by-n-by-3, an alpha channel as the third output, a palette image as indices with the palette as a colormap of values 0 to 1. imfinfo takes the size, mode and format from the same image and the file's size and date from os.stat.
imwrite:
    Python: media.py. Pillow's Image.fromarray of the pixels (doubles scaled by 255 and rounded, logical as black and white, uint16 kept for PNG and TIFF) or of the indices with the colormap as a palette, saved in the format the name or the argument gives; 'Quality' goes to the JPEG encoder and 'Alpha' becomes the image's alpha channel.
audioread, audioinfo:
    Python: media.py. scipy.io.wavfile.read; 8-bit samples are scaled as (x - 128)/128, 16-bit by 1/32768, 32-bit integers by 1/2^31, floating point kept; 'native' keeps the file's class.
audiowrite:
    Python: media.py. scipy.io.wavfile.write: doubles clipped to [-1, 1] and written as 16-bit integers (8-bit, 32-bit integers for 24, or 32- and 64-bit floating point with BitsPerSample).
webread, webwrite, websave, weboptions:
    Python: media.py. In the page, Pyodide's pyfetch (the browser's fetch, so only servers that allow it by CORS answer); elsewhere Python's urllib.request with the timeout. The query is URL-encoded onto the address; webwrite sends name-value pairs as a form, other data as JSON (by jsonencode's rules) and text as it is. The answer is read by its content type (or the ContentType option): JSON by jsondecode's rules, text as characters, an image through Pillow, anything else as a column of uint8. Header fields, a key, and a user name and password (basic authentication) go into the request's headers. weboptions is a value object holding these settings.
# ---- moreplots.py: more plots ----------------------------------------------------------------------
compass, feather:
    Python: moreplots.py. Each arrow drawn as one polyline, the shaft and a two-stroke head a quarter of its length long at 20 degrees, NaN between arrows: from the origin in polar axes (polarplot of their angles and lengths) for compass, from (k, 0) in plain axes for feather, with a dotted line along y = 0.
rose:
    Python: moreplots.py. numpy.histogram of the angles taken modulo 2*pi in nbins (20) equal bins, or in bins about the centres given; each bin's outline is four points (its edges at radius 0 and at its count), the outline plotted by polarplot.
pareto:
    Python: moreplots.py. The values sorted in descending order (stable); bars by bar, as many as it takes for the cumulative sum to reach the threshold (0.95) of the total; xticklabels from the names; then yyaxis right with the cumulative percentage by plot, limits 0 to 100.
stem3:
    Python: moreplots.py. One line holding every stem (from z = 0 to the value, NaN between them) and one line of markers at the values; view(3).
comet, comet3:
    Python: moreplots.py. The whole path as a line and its last point as a filled marker (no animation).
bar3, bar3h, histogram2:
    Python: moreplots.py. Each bar is a box of six quadrilaterals in a patch per series (Faces and Vertices), width 0.8 unless given: detached at x = the series number, grouped side by side, or stacked; bar3h puts the values along x. histogram2 counts with histcounts2 and draws a box over each bin with a count. view(3).
pie3:
    Python: moreplots.py. Each wedge, from 90 degrees clockwise, as patches: its top and bottom faces (the centre and points along the arc every 0.05 radians) and its curved and flat sides, 0.35 high; an exploded wedge is moved out by 0.1 along its middle; its percentage (or label) as text outside it. view(3), axis equal and off.
ribbon:
    Python: moreplots.py. Each column as a surface two points wide, at x = its number +- width/2, coloured by its number.
isosurface:
    Python: moreplots.py. Marching tetrahedra: each cube of the grid is cut into six tetrahedra; where the value crosses the isovalue within one, one triangle (one corner on its own side) or two (two and two) are made, their corners by linear interpolation along the edges, corners on a shared edge made once. Faces and vertices, or a patch drawn with view(3).
slice:
    Python: moreplots.py. A surface on each plane over the grid's other two vectors, coloured by interp3 of the volume at its points.
stream2, stream3, streamline:
    Python: moreplots.py. From each starting point, fourth-order Runge-Kutta steps along the velocity (scipy.interpolate.RegularGridInterpolator, linear, on the grid in meshgrid's layout) normalised so that a step is the step size (0.1) in cells; a line ends at the edge of the grid, where the speed is 0 or not a number, or at maxvert (10000) points. streamline plots the lines.
camorbit, campos:
    Python: moreplots.py. Through view: camorbit adds dtheta to the azimuth and dphi to the elevation (kept within -90 to 90). campos gives the point in the view's direction at ten times the axes' size from the camera target (the middle of the limits unless set), and campos(p) sets the view to look from p at that target.
camtarget, camup:
    Python: moreplots.py. The axes' CameraTarget and CameraUpVector properties (their modes 'auto' until set). The figure drawing in the page projects the 3-D box orthographically from the view's azimuth and elevation; a CameraUpVector set by hand, converted to the plot box's units, is projected onto the screen plane and the view turned about its axis so that it points up; a CameraTarget set by hand is projected and the drawing moved so that it lands in the middle of the axes.
camroll:
    Python: moreplots.py. CameraUpVector turned about the viewing direction (from the target toward the camera, from the view's azimuth and elevation) by Rodrigues' rotation formula, clockwise as seen from the camera so that the picture turns counterclockwise.
coneplot:
    Python: moreplots.py. The field at the points by scipy.interpolate.RegularGridInterpolator over the grid's vectors (linear, nearest or cubic); the typical spacing of the points, the median distance to the nearest neighbour (scipy.spatial.cKDTree), is the length of the fastest cone times s. Each cone is a circle of 12 points round the axis (a quarter of the length in radius) joined to its tip, centred on its point; the triangles of all cones make one patch, its FaceVertexCData the speed. 'quiver' draws a shaft and two barbs instead, as edges only.
streamtube:
    Python: moreplots.py. The streamlines from stream3, and round each a tube: a frame carried along the line by parallel transport (so that it does not twist), with n points on a circle at each vertex, as a surface coloured by z. The divergence of the field (numpy.gradient along each axis, summed) is interpolated onto the line and sets the radius between 0.15 and 0.5 of a grid cell, times scale.
contourslice:
    Python: moreplots.py. The volume interpolated onto each plane's grid (scipy.interpolate.RegularGridInterpolator), its contour lines by the same marching squares as contour, each placed back on its plane in 3-D as a patch with no face whose FaceVertexCData is its level.
butter, cheby1, cheby2, ellip:
    Python: signal.py. scipy.signal.iirfilter with ftype 'butter', 'cheby1', 'cheby2' or 'ellip', btype from ftype (two cutoffs: 'bandpass'), output 'ba', 'zpk' or 'ss' by the number of outputs. Coefficients as rows, zeros and poles as columns.
buttord, cheb1ord, cheb2ord, ellipord:
    Python: signal.py. scipy.signal.buttord, cheb1ord, cheb2ord and ellipord, which give the lowest order and the natural (or edge) frequency as SciPy chooses it.
fir1:
    Python: signal.py. The ideal response from scipy.signal.firwin with a rectangular window and no scaling, times the window (scipy.signal.get_window('hamming', n+1, fftbins=False) unless one is given), then divided by its response at the middle of the first passband (0 when it starts at 0, the Nyquist frequency when it ends there).
fir2:
    Python: signal.py. scipy.signal.firwin2 with a Hamming window (or none, the window given multiplied after) on a grid of npt (512) points.
firls:
    Python: signal.py. scipy.signal.firls with numtaps n+1, the bands and amplitudes as given and fs = 2.
firpm, remez:
    Python: signal.py. scipy.signal.remez (Parks-McClellan) with numtaps n+1, one amplitude per band and fs = 2; type 'hilbert' or 'differentiator' when asked.
kaiserord:
    Python: signal.py. Kaiser's formulas: A = -20*log10(min(dev)), n = ceil((A - 7.95)/(2.285*dw)) with dw the narrowest transition band in rad/sample, beta 0.1102*(A - 8.7) above 50 dB, 0.5842*(A - 21)^0.4 + 0.07886*(A - 21) from 21 dB, else 0; Wn the middles of the transition bands.
filtfilt:
    Python: signal.py. scipy.signal.filtfilt with padtype 'odd' and padlen 3*(max(length(a), length(b)) - 1), or scipy.signal.sosfiltfilt with padlen 3*(2*sections) and the gain applied twice; along the columns (a row vector as a row).
sosfilt:
    Python: signal.py. scipy.signal.sosfilt down the columns.
fftfilt:
    Python: signal.py. scipy.signal.oaconvolve (overlap-add) of the columns with b, cut to the signal's length.
filtic:
    Python: signal.py. scipy.signal.lfiltic, whose state is that of filter's transposed direct form II.
upfirdn:
    Python: signal.py. scipy.signal.upfirdn down the columns.
medfilt1:
    Python: signal.py. For each sample the window from k - floor(n/2) of n samples, zeros beyond the ends (or NaN and numpy.nanmedian for 'truncate'), its median by numpy.median.
sgolay:
    Python: signal.py. S the Vandermonde matrix of the positions -(f-1)/2 ... (f-1)/2 to the powers 0 ... order, G = S*inv(S'*S), B = G*S'.
sgolayfilt:
    Python: signal.py. scipy.signal.savgol_filter with mode 'interp': the first and last (f-1)/2 samples from the polynomial fitted to the first and last frame.
hilbert:
    Python: signal.py. scipy.signal.hilbert down the columns: the FFT, its negative frequencies set to zero and its positive ones doubled, transformed back.
envelope:
    Python: signal.py. The mean m of each column, then m +/- abs(scipy.signal.hilbert(x - m)); for 'peak', the local maxima (and minima) found by scipy.signal.find_peaks at least np apart, with the first and last samples, joined by scipy.interpolate.CubicSpline.
xcorr, xcov:
    Python: signal.py. The shorter signal padded with zeros to the longer's length N, then numpy.correlate in 'full' mode (r(m) = sum of x(n+m)*conj(y(n))) for lags -(N-1) to N-1, scaled as asked; xcov subtracts the means first. A matrix gives every pair of columns.
resample:
    Python: signal.py. p and q divided by their greatest common divisor, then scipy.signal.resample_poly with a Kaiser window of beta 5 (a filter of 20*max(p, q) + 1 taps designed by the window method).
decimate:
    Python: signal.py. scipy.signal.decimate with zero_phase: a Chebyshev type I filter of order 8 (0.05 dB ripple, cutoff 0.8/r) run both ways, or for 'fir' a window-method FIR filter, then every r-th sample from the first.
interp:
    Python: signal.py. The signal extended at each end by odd reflection (repeated for a short one) as far as the filter reaches, scipy.signal.resample_poly by r, the middle kept and its every r-th sample set back to the signal's own.
downsample, upsample:
    Python: signal.py. Slicing: x(phase+1:n:end), and zeros with the samples put at phase+1, n+phase+1, ... (columns for a matrix).
buffer:
    Python: signal.py. Frames taken step n-p apart from the signal with p zeros before it (or skipping -p samples between frames), the last padded with zeros.
findpeaks:
    Python: signal.py. scipy.signal.find_peaks with plateau_size 1 (a flat peak reported at its left edge), then Threshold against the neighbours, MinPeakHeight, scipy.signal.peak_prominences and MinPeakProminence, scipy.signal.peak_widths at half the prominence (or half the height) with the crossings interpolated into x's units, Min/MaxPeakWidth, MinPeakDistance (the highest kept first, each next one only when far enough from those kept), SortStr and NPeaks.
hamming, hann, blackman, flattopwin, blackmanharris, nuttallwin, kaiser, bartlett, triang, rectwin, tukeywin, chebwin, barthannwin, bohmanwin, parzenwin:
    Python: signal.py. scipy.signal.get_window of the matching name ('hamming', 'hann', 'blackman', 'flattop', 'blackmanharris', 'nuttall', ('kaiser', beta), 'bartlett', 'triang', 'boxcar', ('tukey', r), ('chebwin', r), 'barthann', 'bohman', 'parzen') with fftbins False (True for 'periodic'), as a column.
gausswin:
    Python: signal.py. exp(-(alpha*k/((n-1)/2))^2/2) for k from -(n-1)/2 to (n-1)/2.
hanning:
    Python: signal.py. scipy.signal.windows.hann of length n+2 without its two zero ends; the periodic one is hann of length n+1 without its last point.
window:
    Python: signal.py. The window function named by the handle, called with the rest of the arguments.
freqz:
    Python: signal.py. scipy.signal.freqz (scipy.signal.sosfreqz for sections) at n points from 0 (whole: round the circle) or at the frequencies given; with fs, frequencies in Hz.
freqs:
    Python: signal.py. scipy.signal.freqs at the frequencies given (or 200 it chooses).
impz, stepz:
    Python: signal.py. scipy.signal.lfilter (or sosfilt) of a unit impulse; the step response its cumulative sum. Without n: an FIR filter's length, or the samples until the response stays below 5e-5 of its largest (of the first 5000).
grpdelay:
    Python: signal.py. scipy.signal.group_delay at n frequencies from 0 to pi.
zplane:
    Python: signal.py. scipy.signal.tf2zpk for coefficients; the unit circle, the zeros as o and the poles as x, axis equal.
tf2zp, zp2tf, tf2sos, zp2sos, sos2tf, sos2zp:
    Python: signal.py. scipy.signal.tf2zpk, zpk2tf, tf2sos, zpk2sos, sos2tf and sos2zpk. With a gain output, the gain g is the product of the sections' first coefficients, each section's numerator divided by its own. The order in which SciPy pairs poles and zeros into sections is SciPy's.
filtord:
    Python: signal.py. The longer of b and a (trailing zeros dropped) less 1, or a digital filter's order.
designfilt:
    Python: signal.py. A digitalFilter object. FIR with FilterOrder: scipy.signal.firwin with a rectangular window times the window, scaled as fir1 scales; from passband and stopband edges: scipy.signal.kaiserord with the stopband attenuation (60 dB) and the transition width, then firwin with that Kaiser window. IIR: scipy.signal.iirfilter (butter unless DesignMethod says cheby1, cheby2 or ellip) with output 'sos', or scipy.signal.iirdesign from the edges, ripple (1 dB) and attenuation (60 dB). filter(d, x) uses scipy.signal.sosfilt or lfilter.
lowpass, highpass, bandpass, bandstop:
    Python: signal.py. PyLAB's own design: a transition band (1 - Steepness) of the way from the passband edge to the nearest end (for a band, the narrowest side), scipy.signal.kaiserord for the stopband attenuation (60 dB) and that width, scipy.signal.firwin with the Kaiser window and the cutoff in the middle of the transition band; the signal, padded with zeros, filtered by scipy.signal.lfilter and shifted back by the filter's delay (numtaps - 1)/2. A second output is the digitalFilter.
periodogram:
    Python: signal.py. scipy.signal.periodogram with the window (rectangular unless given), nfft = max(256, 2^nextpow2(N)), no detrending and density scaling; fs = 2*pi when none is given, so frequencies are in rad/sample.
pwelch, cpsd, mscohere, tfestimate:
    Python: signal.py. scipy.signal.welch, csd (of y and x, so Pxy = X.*conj(Y)), coherence and csd(x, y)/welch(x) with segments of floor(N/4.5) samples (8 segments with half overlapping), a symmetric Hamming window, noverlap half a segment, nfft = max(256, 2^nextpow2(segment)), no detrending, mean averaging; fs = 2*pi when none is given.
spectrogram:
    Python: signal.py. scipy.signal.stft with the same segments as pwelch, no boundary padding, multiplied back to the windowed segments' plain FFT sums; ps from scipy.signal.spectrogram's density; t the segments' middles (in samples without fs).
bandpower:
    Python: signal.py. The mean of abs(x).^2; with fs, scipy.signal.periodogram with a Hamming window and nfft = N, then the densities in the range times their bin widths, summed.
chirp:
    Python: signal.py. scipy.signal.chirp with phi in degrees.
sawtooth, square:
    Python: signal.py. scipy.signal.sawtooth(t, xmax) and scipy.signal.square(t, duty/100).
rectpuls, tripuls:
    Python: signal.py. 1 for -w/2 <= t < w/2; the triangle rising linearly from -w/2 to s*w/2 and falling to w/2.
gauspuls:
    Python: signal.py. scipy.signal.gausspulse with retquad and retenv.
diric:
    Python: signal.py. sin(n*x/2)./(n*sin(x/2)), with (-1)^(k*(n-1)) at x = 2*pi*k.
db2mag, mag2db, pow2db, db2pow:
    Python: signal.py. 10^(y/20), 20*log10(y), 10*log10(y) and 10^(y/10); a negative magnitude or power gives NaN.
peak2peak, peak2rms:
    Python: signal.py. max - min (of the magnitudes for complex values) and max(abs(x))/sqrt(mean(abs(x).^2)) along the first dimension whose size is not 1.
rceps:
    Python: signal.py. real(numpy.fft.ifft(log(abs(numpy.fft.fft(x))))); the minimum-phase signal from the cepstrum folded onto its positive times and exponentiated back.
dct, idct:
    Python: signal.py. scipy.fft.dct and idct with norm 'ortho' (type 2 unless asked) along the first dimension whose size is not 1.
fitlm:
    Python: regression.py. The formula (or model spec) is expanded into terms: a*b gives every product of the factors' subsets, a:b one product, a^k the powers up to k with their products, and - removes terms; a categorical variable gives a dummy column for each level but the first, named var_level. The design matrix is solved by numpy.linalg.lstsq on the rows weighted by the square roots of the weights, the covariance is the residual variance times pinv(X'WX), and t, p, R-squared, the log-likelihood and the criteria follow from the residuals. Terms keep the order of the variables in the table. 'RobustOpts' runs robustfit's iteratively reweighted least squares and takes the final weights into the covariance.
fitglm, glmfit:
    Python: regression.py. Iteratively reweighted least squares from mu started at (N*y + 0.5)/(N + 1) for the binomial, y + 0.25 for the Poisson, or y: the working response eta + (y - mu)*g'(mu) solved with weights w/(g'(mu)^2 V(mu)) by numpy.linalg.lstsq, until the deviance changes by less than 1e-10 of itself (at most 100 times). V is mu(1 - mu)/N, mu, mu^2 or mu^3. The dispersion is 1 for the binomial and Poisson (unless DispersionFlag or estdisp asks), else the Pearson chi-square over the error degrees of freedom; the covariance is it times the inverse of X'WX, with normal p-values when the dispersion is fixed and t otherwise.
fitnlm, nlinfit:
    Python: regression.py. scipy.optimize.least_squares with the Levenberg-Marquardt method (trust region reflective when there are fewer observations than coefficients) on the weighted residuals, tolerances 1e-8; the Jacobian at the answer by forward differences; MSE is the weighted residual sum of squares over n - p and the covariance MSE*pinv(J'WJ).
predict:
    Python: regression.py. For a linear model the design matrix of the new rows times the coefficients; the bounds are t(1 - alpha/2, DFE) (or, simultaneous, the square root of p*F(1 - alpha, p, DFE)) times the square root of x*Cov*x' (plus MSE for 'observation'). For a generalized linear model the inverse link of the linear predictor, the bounds taken through the inverse link; for a nonlinear model the model function and its Jacobian by forward differences. Of a classification or regression model from fitc.../fitr...: mlmodels.py, its scores.
coefCI:
    Python: regression.py. Each coefficient plus and minus t(1 - alpha/2, DFE) times its standard error (the normal quantile for a generalized linear model of fixed dispersion).
coefTest:
    Python: regression.py. F = (Hb - c)'(H Cov H')^-1 (Hb - c)/r, with r the rank of H, against the F distribution with r and DFE degrees of freedom.
anova:
    Python: regression.py. Each term's sum of squares is how much the residual sum of squares grows when that term's columns are taken out (the others kept); F is its mean square over the error mean square. 'summary' splits the total sum of squares about the mean into model and residual.
plotResiduals:
    Python: regression.py. histogram, plot or normplot of the raw residuals, as asked.
regress:
    Python: regression.py. numpy.linalg.lstsq; bint from the covariance s^2 pinv(X'X) and t(1 - alpha/2, n - p); rint each residual plus and minus t(1 - alpha/2, n - p - 1) times the standard deviation with that row left out times sqrt(1 - h); stats [R^2, F, p, s^2] with R^2 from the sum of squares about the mean.
robustfit:
    Python: regression.py. Least squares to start, then repeatedly: the residuals divided by sqrt(1 - h) (h the leverages of the weighted design), the scale s = median of their absolute values (the p - 1 smallest left out)/0.6745, the weights wfun(r/(tune*s)), and weighted least squares again, until no coefficient moves by more than 1e-6 of the largest (at most 50 times). The tuning constants are bisquare 4.685, andrews 1.339, cauchy 2.385, fair 1.400, huber 1.345, logistic 1.205, talwar 2.795 and welsch 2.985.
ridge:
    Python: regression.py. The predictors centred and divided by their standard deviations (n - 1), the response centred, and (Z'Z + k I) b = Z'y solved for each k; scaled 0 divides b by the standard deviations and puts mean(y) - mean(X)*b first.
glmval:
    Python: regression.py. The inverse link of [1 X]*b (X*b with 'constant' 'off') plus the offset, times size; the bounds from the covariance in stats through the inverse link, with t(1 - (1 - confidence)/2, dfe) when the dispersion was estimated and the normal quantile when not.
nlparci:
    Python: regression.py. beta plus and minus t(1 - alpha/2, n - p) times the square roots of the diagonal of the covariance, given or made from the Jacobian as (R'R/(n - p))*pinv(J'J).
nlpredci:
    Python: regression.py. The model at X, its Jacobian in the coefficients by forward differences, and delta = t(1 - alpha/2, n - p) (or with SimOpt the square root of p*F) times the square root of J*Cov*J' (plus the MSE for 'observation').
partialcorr:
    Python: regression.py. For X alone the inverse of its correlation matrix P, rho = -P_ij/sqrt(P_ii P_jj); with z, the correlation of the residuals of x and y after least squares on [1 z]. The p-values from t = rho sqrt(df/(1 - rho^2)) with df = n - 2 - the number of variables held fixed. 'Spearman' ranks each column first (scipy.stats.rankdata).
randg:
    Python: regression.py. gamrnd(a, 1), drawn from the language's random number generator.
fit:
    Python: curvefit.py. A model linear in its coefficients (poly, a cell of terms) is solved by numpy.linalg.lstsq on the weighted rows; others by scipy.optimize.least_squares with the trust region reflective method (bounds from Lower and Upper, scaled by the Jacobian, tolerances 1e-8 or TolFun, MaxFunEvals 600), starting from StartPoint or a start worked out from the data: exp1 from a line through log|y|, power from a line in log-log, gauss from the largest peaks and the widths above half their heights (each taken off before the next), sin and fourier from the strongest frequencies in the FFT of the data resampled evenly, rat from least squares of y times the denominator, weibull from a = 1, b = 2. Without a start, every coefficient starts at 1, with a warning. Robust 'Bisquare' and 'LAR' reweight the fit as robustfit does (bisquare weights of the leverage-adjusted residuals over the median absolute deviation, or 1/|r|) until the coefficients stop moving. confint and predint use the covariance from the residual variance and the Jacobian. Interpolants are numpy.interp, scipy.interpolate.interp1d ('nearest'), PchipInterpolator and CubicSpline (not-a-knot).
    smoothingspline: PyLAB's own: the Reinsch form (Green and Silverman) of the spline minimizing p*sum(w r^2) + (1 - p)*integral(f''^2), solved with a banded Cholesky factor (scipy.linalg.cholesky_banded), then the natural cubic spline through the fitted values. Without SmoothingParam, p is chosen by generalized cross-validation: n*sum(w r^2)/trace(I - A)^2, with the trace from the band of the inverse (Hutchinson and de Hoog), over a grid of 31 values of lambda = (1 - p)/p and refined around the best; fits with less than one residual degree of freedom are left out. With unit weights this is SciPy's make_smoothing_spline choice.
fittype:
    Python: curvefit.py. A library name gives the model's formula, coefficients and start; an expression is made elementwise (* / ^ as .* ./ .^) and compiled as an anonymous function of its coefficients and x; a cell of terms becomes a basis of columns for a linear model.
fitoptions:
    Python: curvefit.py. A struct of Method, Robust, StartPoint, Lower and Upper (Method from the model's kind), with the options given; fit reads its fields as it reads options given by name.
confint:
    Python: curvefit.py. Each coefficient plus and minus t((1 + level)/2, dfe) times its standard error.
predint:
    Python: curvefit.py. The Jacobian of the model in the coefficients at x (the basis for a linear model, forward differences otherwise), the variance J*Cov*J' (plus the residual variance for 'observation'), and t((1 + level)/2, dfe), or for simopt 'on' the square root of k*F(level, k, dfe) with k the number of coefficients (one more for 'observation').
coeffvalues, coeffnames, numcoeffs:
    Python: curvefit.py. The fit's coefficients and their names as the model has them.
differentiate:
    Python: curvefit.py. numpy.polyder for a polynomial, the spline's own derivatives for an interpolant or smoothing spline, and otherwise central differences extrapolated from steps of 1e-3*max(|x|, 1) and half that.
integrate:
    Python: curvefit.py. numpy.polyint for a polynomial, the spline's own integral for an interpolant or smoothing spline, and otherwise scipy.integrate.quad.
smooth:
    Python: curvefit.py. 'moving': the mean over the span (made odd), the window narrowing symmetrically at the ends. 'lowess' and 'loess': at each point a line (or a quadratic) fitted by weighted least squares to the span nearest points with tricube weights (1 - (d/dmax)^3)^3; 'rlowess' and 'rloess' then five more passes with bisquare weights of the residuals over 6 times their median absolute value. 'sgolay': scipy.signal.savgol_filter with mode 'interp'.
islocalmax, islocalmin:
    Python: datafeatures.py. Runs of equal values higher than both neighbours (never touching an end); the prominence from scipy.signal.peak_prominences at the run's first sample; then MinProminence, MinSeparation (in the sample points, the most prominent first), MaxNumExtrema, and FlatSelection for where in the run to mark. islocalmin is islocalmax of -A.
ischange:
    Python: datafeatures.py. PyLAB's own: the segmentation of least total cost, each change costing Threshold: optimal partitioning with PELT's pruning (Killick, Fearnhead and Eckley) for 'mean', where a segment's cost is its sum of squared residuals about its mean; for 'linear' the squared residuals about its least-squares line (segments of at least 2), and for 'variance' its length times the log of its variance about its mean (segments of at least 3, the variance kept above a millionth of the data's), searched without pruning. MaxNumChanges uses dynamic programming over the number of segments and keeps the cheapest with at most that many changes.
trenddecomp:
    Python: datafeatures.py. PyLAB's own. 'ssa': the trajectory (Hankel) matrix of lag L (half the data unless given), numpy.linalg.svd, and each elementary component reconstructed by diagonal averaging. Components whose singular value is at or below the Gavish-Donoho hard threshold (omega(beta) times the median singular value) stay in the remainder; of the rest, those with less than one cycle in L samples (the largest frequency of their FFT) form the long-term trend, and the others are summed by period into seasonal trends, the largest first. 'stl': seasonal-trend decomposition by loess (Cleveland and others) with the inner loop run twice and no robustness passes: cycle-subseries smoothed by loess over 7 points, low-pass filtered by moving averages of the period, the period and 3 and a loess, and the trend by loess over the next odd number above 1.5*period/(1 - 1.5/7); several periods are taken off one after another.
xline, yline, xregion, yregion:
    Python: charts.py. A line (or patch) object marked to span: the page draws it from one edge of the axes to the other at the limits it has when drawing, so it follows zoom and pan, and the limits are worked out without it. The label is drawn beside the line at its top (or as asked), turned along a vertical line.
heatmap:
    Python: charts.py. An image of the colour data (scaled to ColorLimits through the colormap, parula unless given) with a text for each cell in white or black by the cell's brightness, ticks and labels for the rows and columns, and a colorbar. From a table, the rows are grouped by the two variables (categories in their order, other values sorted) and counted or summarized.
boxchart:
    Python: charts.py. For each group: the quartiles by quantile, whiskers to the farthest values within 1.5 times the box's height, the others as markers; a notch of 1.57 times the box's height over the square root of the count. Groups by colour sit side by side.
swarmchart, swarmchart3:
    Python: charts.py. PyLAB's own spreading: for each x, offsets drawn uniformly from the language's random numbers, scaled by the points' Gaussian kernel density in y (Silverman's bandwidth) relative to its largest, to half of XJitterWidth; then scatter.
piechart, donutchart:
    Python: charts.py. Each wedge a patch from the start angle (90 degrees, clockwise unless asked), its share of the total; labels beyond the rim; a donut leaves InnerRadius of the radius empty.
stackedplot:
    Python: charts.py. An axes for each numeric variable (or column), stacked from the top of the figure down, plotted against the row times, XVariable or the row numbers; only the bottom axes shows its x tick labels.
plotyy:
    Python: charts.py. yyaxis left with the first plot, yyaxis right with the second, the two axes given back.
polarhistogram:
    Python: charts.py. numpy.histogram of the angles taken modulo 2*pi over the edges (nbins evenly over 0 to 2*pi; without them about 2*n^(1/3) bins, at most 50), each bin a wedge patch drawn by the page in polar axes.
binscatter:
    Python: charts.py. numpy.histogram2d over the data's limits (about sqrt(n)/2 bins each way, 10 to 300, unless given), the bins that hold points as faces of one patch coloured from the colormap by count.
parallelplot:
    Python: charts.py. Each coordinate scaled to its range (or as DataNormalization asks), a line for each row through the coordinates, one per group in the colour order.
scatterhistogram:
    Python: charts.py. scatterhist with the groups, labels and title.
wordcloud:
    Python: charts.py. PyLAB's own layout: font sizes from 10 to 40 points by size, the words placed largest first along a spiral at the first spot where their box (0.6 of the size per character wide) overlaps no other.
fimplicit3:
    Python: volumes.py. The function evaluated on a 35 by 35 by 35 grid of the box and the zero isosurface taken by isosurface's marching tetrahedra, coloured by z.
tetramesh:
    Python: volumes.py. Each tetrahedron as a patch of its four triangles, its colour index the colormap's.
isocaps:
    Python: volumes.py. On each face of the volume, each grid cell clipped to where V is above (or below) the value, the cut points interpolated along the cell's edges, and the polygons fanned into triangles coloured by V.
isonormals:
    Python: volumes.py. numpy.gradient of V on its grid, interpolated at the vertices (scipy.interpolate.RegularGridInterpolator), negated.
smooth3:
    Python: volumes.py. scipy.ndimage.correlate with the box (or Gaussian, normalized) kernel, mode 'nearest'.
reducevolume, subvolume, volumebounds:
    Python: volumes.py. Every R-th sample; the samples within the limits; the extremes of the grid and the finite values.
reducepatch:
    Python: volumes.py. PyLAB's own vertex clustering: the vertices merged on a grid over the patch's box (each cell's to their mean), faces whose corners merged dropped and repeated faces kept once, the grid's size chosen by bisection so that the faces left come to the number asked or just above it.
streamslice:
    Python: volumes.py. PyLAB's own evenly spaced lines: from seeds on a grid (12 by 12 times the density), lines traced both ways by fourth-order Runge-Kutta on the normalized field (RegularGridInterpolator), stopping at the edge, at a still point, or in a cell of a 25-by-25 (times density) grid another line has passed; an arrowhead at each line's middle.
streamparticles:
    Python: volumes.py. Markers at every k-th vertex of the lines (k so that there are about n), moved one vertex along at each frame (drawnow and pause at FrameRate) when animated.
mink, maxk:
    Python: datamore.py. A stable sort along the dimension with NaN last (by absolute value for 'abs'), the first k kept with their places.
clip:
    Python: datamore.py. min(max(A, lower), upper), NaN kept; integers rounded and saturated.
allfinite, anynan:
    Python: datamore.py. all(isfinite) and any(isnan) over all elements.
isuniform:
    Python: datamore.py. The step (last - first)/(n - 1); uniform when every difference is within 4*eps(the largest magnitude) times n of it (single's eps for single).
rmoutliers:
    Python: datamore.py. isoutlier with the same method and options; the elements (or rows with at least MinNumOutliers outliers, or columns for dim 2) left out.
cbrt:
    Python: datamore.py. numpy.cbrt.
interpft:
    Python: datamore.py. The FFT along the dimension, zeros inserted in the middle (the Nyquist term of an even length split between both halves), the inverse FFT times n/m; for n below m, interpolated to a multiple of n and every k-th taken.
resize, paddata, trimdata:
    Python: datamore.py. numpy.pad ('constant', 'edge', 'wrap', 'symmetric', 'reflect') or slicing along each dimension, at the trailing, leading or both sides; tables by rows of missing values or taken rows.
groupcounts:
    Python: datamore.py. The rows grouped by the variables' values (sorted as sort sorts them) and counted, percentages of all rows.
grouptransform:
    Python: datamore.py. The method applied to each group's rows of each data variable: zscore (mean and std, n - 1), norm (2-norm), meancenter, rescale (to 0..1), meanfill, linearfill (interpolation by row order), or the function.
groupfilter:
    Python: datamore.py. The function called with each group's column; a false scalar drops the group, a logical vector its rows.
pivot:
    Python: datamore.py. Rows grouped by Rows and Columns; the method over the DataVariable's values in each pair (0 for count and sum where none fall, NaN otherwise); the column groups' names made valid as variable names.
topkrows:
    Python: datamore.py. A stable lexicographic sort by the columns asked (descending unless 'ascend'), the first k rows.
lag:
    Python: datamore.py. Each variable's rows moved by n, missing values (NaN, NaT, <undefined>, "" or empty) put where nothing comes.
pattern, digitsPattern, lettersPattern, alphanumericsPattern, whitespacePattern, wildcardPattern, characterListPattern, optionalPattern, asManyOfPattern, asFewOfPattern, letterBoundary, digitBoundary, alphanumericBoundary, whitespaceBoundary, lineBoundary, textBoundary, lookAheadBoundary, lookBehindBoundary, regexpPattern, caseInsensitivePattern, caseSensitivePattern, namedPattern:
    Python: patterns.py. Each pattern is held as a Python regular expression: digits [0-9]+, letters [^\W\d_]+, wildcard [\s\S]+? (lazy), counts as {n} or {min,max}, boundaries as lookarounds, regexpPattern through regexp's own translation, caseInsensitivePattern as (?i:...); + joins them, | and arrays give alternatives, and text is matched literally (re.escape).
extract:
    Python: patterns.py. re.finditer's matches of the pattern.
symmlq:
    Python: krylov.py. PyLAB's own implementation of Paige and Saunders' SYMMLQ: the preconditioned Lanczos process (M-inner products), the LQ factorization of its tridiagonal matrix by Givens rotations, x updated along the rotated Lanczos vectors; it stops when the residual of the iterate, or of the CG point beside it, meets the tolerance. Through the same wrapper as pcg: flag, relres, iter and resvec as there.
bicgstabl:
    Python: krylov.py. PyLAB's own implementation of BiCGStab(l) of Sleijpen and Fokkema with l = 2: two BiCG steps, then the minimal-residual polynomial of degree 2 by modified Gram-Schmidt; right preconditioning (x = M\y).
parfeval, parfevalOnAll, backgroundPool, fetchOutputs, fetchNext, afterEach, afterAll, cancel:
    Python: futures.py. PyLAB runs the function when parfeval is called, in the engine (programs here run one computation at a time), so the future is finished at once with its outputs or its error. fetchOutputs puts each output of several futures together with vertical concatenation (or in cells); afterEach and afterAll run their function at once on those outputs.
memoize, clearCache, clearAllMemoizedCaches, stats:
    Python: futures.py. Results kept in a dictionary keyed by the number of outputs and the inputs' serialized bytes, the least recently used dropped beyond CacheSize; handles to named functions give the same memoized function.
timeit:
    Python: futures.py. One warm-up call, then up to 11 timed batches (enough calls for about 0.2 s in all), the median time per call (time.perf_counter).
setpref, addpref, getpref, ispref, rmpref:
    Python: futures.py. A JSON file .pylab-prefs.json in the home folder (the page's /home/user, kept in the browser), each value serialized as the parallel pool serializes values.
audioplayer, play, playblocking, isplaying, resume:
    Python: audioobjs.py. The samples go to the page, which plays them through its Web Audio context (resampled to the context's rate); pause and stop end the sound there, and where a player is is worked out from the time since play.
audiorecorder, record, recordblocking, getaudiodata, isrecording:
    Python: audioobjs.py and pylab-app.js. The page asks the browser for the microphone (getUserMedia, without echo cancellation, noise suppression or gain control) and records it through an AudioContext at the rate asked for; the samples come to the engine when the recording is stopped or asked for.
detectImportOptions, setvartype, setvaropts, getvaropts, readvars:
    Python: importopts.py. The file is read as readtable reads it, and the options hold its variables' names and types (double, logical, char, string, categorical, datetime, duration), the delimiter (the most frequent of , tab ; | in the first line), and where the names and the data are. Read with options, the table is read again from those lines, renamed, each variable converted to its type (FillValue for missing numbers), and the selected variables kept in their order.
xmlread, xmlwrite, com.mathworks.xml.XMLUtils.createDocument:
    Python: importopts.py. xml.dom.minidom parses the file (no external entities are fetched); the document's nodes answer the DOM methods by name, a method with arguments waiting to be called (node.getAttribute('id')); xmlwrite is minidom's toprettyxml with three spaces of indent, blank lines left out.
bwmorph:
    Python: imageproc.py. PyLAB's own versions: thin and skel by Zhang and Suen's thinning, shrink by thinning and then taking off end points; the others from the eight neighbours of each pixel (clean, fill, majority, remove, spur, endpoints, branchpoints, bridge, diag, hbreak) or by dilation and erosion with a 3-by-3 square.
bwboundaries:
    Python: imageproc.py. Moore-neighbour tracing, clockwise, from each object's first pixel down the columns, stopping by Jacob's criterion; holes are the background components (4-connected for 8-connected objects) that do not touch the edge, traced the same way.
imresize:
    Python: imageproc.py. Separable resampling: for each output row (then column) at x = u/scale + 0.5*(1 - 1/scale), the kernel's weights over the nearest input samples, normalized to add up to 1, the input mirrored at its ends; shrinking with antialiasing stretches the kernel by 1/scale. Kernels: Keys' cubic (a = -0.5) for bicubic, the triangle for bilinear, the box for nearest, and Lanczos. Integer images are rounded and saturated at the end.
imrotate:
    Python: imageproc.py. Quarter turns by numpy.rot90. Other angles: each output pixel mapped back through the rotation about the image centres and sampled from A, nearest, bilinear or Keys' cubic, with zeros outside; 'loose' sizes the output to the turned corners (ceil of the turned width and height).
imcrop:
    Python: imageproc.py. Columns round(xmin) to round(xmin + width) and rows round(ymin) to round(ymin + height), cut to the image.
imtranslate:
    Python: imageproc.py. Whole shifts move the pixels; others sample A at the shifted points (bilinear unless asked), FillValues outside.
imfilter:
    Python: imageproc.py. Each plane padded by the boundary rule (numpy.pad: 'symmetric', 'edge' for replicate, 'wrap' for circular, or a constant), then scipy.signal.correlate in 'valid' mode with the kernel (turned half round for 'conv'), its centre at floor((size + 1)/2).
fspecial:
    Python: imageproc.py. average: ones/n. gaussian: exp(-(x^2 + y^2)/(2 sigma^2)) normalized (values under eps of the peak set to 0). log: that Gaussian times (x^2 + y^2 - 2 sigma^2)/sigma^4, less its mean. laplacian and unsharp: the 3-by-3 forms of alpha. disk: PyLAB's own exact area of each pixel inside the circle, by scipy.integrate.quad, normalized. motion: PyLAB's own: the length of a centred segment of length len at theta inside each pixel (Liang-Barsky clipping), normalized.
imgaussfilt:
    Python: imageproc.py. Two one-dimensional Gaussians (each normalized) as one kernel, filtered as imfilter does with 'replicate' padding.
medfilt2:
    Python: imageproc.py. The image padded (zeros, mirrored, or ones), then numpy.median over each m-by-n window (numpy.lib.stride_tricks.sliding_window_view), the window's centre at floor((size + 1)/2).
edge:
    Python: imageproc.py. PyLAB's own versions of the methods. sobel, prewitt and roberts: the gradients by the kernels (divided by 8, 6 and 2) with replicated edges; the threshold, unless given, the square root of 4 times the mean squared gradient; edges are the pixels above it that are local maxima across the edge (along x where the x gradient is the larger), unless 'nothinning'. log and zerocross: the image filtered (fspecial log with sigma 2 and size 2*ceil(3 sigma) + 1, or h) and the sign changes to a right or lower neighbour by more than the threshold (0.75 times the mean absolute response unless given), marked on the side nearer zero. canny: derivative-of-Gaussian gradients (sigma sqrt(2)), the magnitude scaled to 1, non-maximum suppression along the gradient with interpolated neighbours, and hysteresis: the high threshold where 70 % of a 64-bin histogram of magnitudes lies below, the low 0.4 times it, weak edges kept when 8-connected to a strong one.
stretchlim:
    Python: imageproc.py. The cumulative histogram of each plane (256 bins, 65536 for 16-bit), the first bin above tol(1) and the first at tol(2), as fractions of the range ([0 1] when they meet).
imadjust:
    Python: imageproc.py. (clip(I, low_in, high_in) - low_in)/(high_in - low_in), raised to gamma, scaled to low_out .. high_out, on values from 0 to 1 and back to the class.
imhist:
    Python: imageproc.py. The values scaled to 0..1 and counted by numpy.bincount of round(value*(n - 1)); with no output, stem draws the counts.
histeq:
    Python: imageproc.py. PyLAB's own: the cumulative histogram (256 bins, 65536 for 16-bit) as the transform, rounded to n levels: T = round(cdf*(n - 1))/(n - 1).
graythresh:
    Python: imageproc.py. Otsu's method on a 256-bin histogram: the bin k that maximizes the between-class variance (the mean of the bins when several do), level = (k - 1)/255, EM that variance over the total variance.
imbinarize:
    Python: imageproc.py. The values from 0 to 1 compared with graythresh's level or the threshold given.
imcomplement:
    Python: imageproc.py. intmax + intmin - I for integers, 1 - I for floating point, ~I for logical.
strel:
    Python: imageproc.py. disk: x^2 + y^2 <= r^2; diamond |x| + |y| <= r; octagon |x| + |y| <= 2r - (2r/3) within the square; line: the rounded points of a centred segment; square and rectangle all ones.
imdilate, imerode, imopen, imclose:
    Python: imageproc.py. Flat morphology: the image padded with -Inf (dilation) or +Inf (erosion) and the maximum (or minimum) of its shifts by each element of the structuring element (reflected for dilation), the element's centre at floor((size + 1)/2); opening and closing in turn.
imfill:
    Python: imageproc.py. 'holes': scipy.ndimage.binary_fill_holes with 4-connectivity (8 with conn 8); locations: the background components (scipy.ndimage.label) holding them set.
bwlabel, bwconncomp:
    Python: imageproc.py. scipy.ndimage.label with 8- (or 4-) connectivity, renumbered in the order of each component's first pixel down the columns.
regionprops:
    Python: imageproc.py. From each region's pixel coordinates: the centroid; second moments with 1/12 added for the pixels' extent, giving MajorAxisLength and MinorAxisLength (2 sqrt(2) sqrt(uxx + uyy +- common)), Eccentricity and Orientation (degrees, from the x axis, y upwards); BoundingBox from the extremes; ConvexArea the pixels whose centres lie in the convex hull of the pixel squares (scipy.spatial.ConvexHull); FilledArea after binary_fill_holes. 'table' gives a table.
imtile, montage:
    Python: imageproc.py. Each image scaled to 0..1, resized to the first one's size (or ThumbnailSize) by imresize, and placed row by row in a grid of about sqrt(K*h/w) columns unless GridSize says; montage shows the result with imshow.
h5create, h5write, h5read, h5readatt, h5writeatt, h5info, h5disp:
    Python: hdf5.py. h5py (loaded the first time in the page): datasets are made with h5py's create_dataset (maxshape None where size is Inf, gzip for Deflate), arrays written and read with their dimensions reversed (numpy transpose) so that the language's column order matches HDF5's row order; start, count and stride become slices; variable-length strings come back as text.
readstruct, writestruct:
    Python: datafiles.py. XML through Python's xml.etree.ElementTree: children become fields (numbers where the text is one, else strings), attributes fields with the suffix, text beside them Text, and repeated elements arrays or struct arrays; writestruct writes the same layout with three spaces of indent. JSON through jsondecode and jsonencode.
xlsread, xlswrite, xlsfinfo:
    Python: datafiles.py and tables.py. The sheet's cells read from the .xlsx file's XML (shared strings, numbers, booleans); num is trimmed to the rows and columns holding numbers, txt to those holding text. xlswrite reads every sheet of an existing file, puts the values in place and writes the workbook again, values only.
readtimetable:
    Python: datafiles.py. readtable, then table2timetable with the row times from the first datetime or duration variable (or RowTimes).
stack, unstack:
    Python: tablestack.py. stack: each row repeated once for each stacked variable, an indicator categorical whose categories are their names, and their values interleaved. unstack: rows grouped by the grouping variables (sorted), a variable for each indicator value (categories in their order, text and numbers sorted), several values summed (or given to the AggregationFunction), none a missing value; names made valid unless VariableNamingRule is 'preserve'.
animatedline, addpoints, clearpoints, getpoints:
    Python: animation.py. A line object whose Type reads 'animatedline': addpoints appends to its data (dropping the oldest beyond MaximumNumPoints) and marks the figure to be drawn again, which the page does at drawnow or when the program ends.
VideoWriter, writeVideo:
    Python: animation.py. AVI files written by PyLAB itself (RIFF: hdrl with avih, strh and strf, a movi list, an idx1 index), each frame a JPEG from Pillow at Quality (Motion JPEG), BGR rows bottom-up padded to 4 bytes (uncompressed), or 8-bit gray with a gray palette. The header is written again at close with the frame count.
VideoReader, hasFrame, readFrame, read:
    Python: animation.py. The AVI file's chunks are read for the first video stream's size, rate and frames (00dc or 00db, inside rec lists too), each frame decoded when asked (Pillow for JPEG, the rows for uncompressed and 8-bit); animated GIFs through Pillow, the frame rate from the first frame's duration.
dbstop, dbclear, dbstatus:
    Python: devtools.py and worker_api.py. The breakpoints are the same the Editor's margin sets: the file found on the path, the line moved to the next line where a statement begins (from the parsed file), the page told so that the Editor shows them. 'if error': when an error ends a command, the run stops at the innermost function of the program where it was raised, with its workspace and the K>> prompt, after the error is shown.
dbstack:
    Python: devtools.py and runtime.py. The program's function frames on Python's stack, innermost first, with the line each is at.
checkcode, mlint:
    Python: devtools.py. PyLAB's own checks: the file parsed as the engine parses it (a syntax error is the only message then); in each function, a name assigned but never read anywhere in it (nor in its nested functions, nor where eval or the like might read it), a parameter never read, an output never assigned, an assignment or expression (not a call) without a semicolon; and a function file whose first function is named unlike the file. The ids are NASGU, INUSD, STOUT, NOPRT, FNDEF and SYNTAX.
clipboard:
    Python: devtools.py. The page's navigator.clipboard (writeText, readText); outside a page, a clipboard of the engine's own.
lookfor:
    Python: devtools.py. The first comment line of each program file on the path and the first line of each built-in's help, searched for the topic (case ignored); -all searches all of the help.
datetick:
    Python: devtools.py. PyLAB's own tick choice: years (1, 2, 5, 10 ...) over three years of range, months (1, 2, 3, 4, 6 or 12) over 45 days, else days or parts of a day (14 days down to a minute), about 4 to 8 ticks; labels from datestr, as 'yyyy', 'mmmyy', 'mmm', 'dd-mmm' or 'HH:MM' unless a format is given.
# ---- graphs.py: graphs and networks ----------------------------------------------------------------------------------------------
graph, digraph:
    Python: graphs.py. A value object of PyLAB's own holding the node count, names (or none), the end nodes of each edge as NumPy integer arrays, the weights (or none) and the other node and edge variables; the edges sorted by end nodes with numpy.lexsort (a graph's ends ordered first). Nodes and Edges are tables made when asked.
numnodes, numedges, findnode, findedge, degree, indegree, outdegree, neighbors, successors, predecessors, outedges, inedges, edgecount, ismultigraph:
    Python: graphs.py. Counts and searches over the edge arrays, edges in their stored order.
adjacency, incidence:
    Python: graphs.py. scipy.sparse.coo_matrix from the end nodes (a graph's edges both ways, parallel edges summed), made into the language's sparse matrix.
addedge, rmedge, addnode, rmnode, subgraph, reordernodes, flipedge:
    Python: graphs.py. New edge and node arrays, the edges sorted again; subgraph and rmnode keep the edges whose ends both stay, renumbered.
shortestpath, distances, nearest, shortestpathtree:
    Python: graphs.py. PyLAB's own searches: breadth first without weights, Dijkstra's method with a binary heap (Python's heapq) for weights of one sign, Bellman and Ford's for negative weights (an error if a pass still improves after n - 1). Of equal paths, the first found keeps its predecessor.
bfsearch, dfsearch, allpaths:
    Python: graphs.py. Breadth-first (a deque) and depth-first (an explicit stack) searches, neighbours in the order of their numbers; allpaths a depth-first walk that does not revisit a node on its path.
conncomp, biconncomp, condensation:
    Python: graphs.py. Weak components by union-find over the edges; strong components by Tarjan's method, without recursion; biconnected components by Hopcroft and Tarjan's depth-first search with a stack of edges. Components renumbered by their first node (or edge).
toposort, isdag, hascycles:
    Python: graphs.py. Kahn's method with a heap, so the smallest free node comes next; a graph (undirected) has a cycle when it has a self-loop or more edges than nodes less components.
transclosure, transreduction:
    Python: graphs.py. Breadth-first reach from each node; the reduction through the condensation, an edge kept when no other component lies on a path between its ends.
minspantree:
    Python: graphs.py. Prim's method with a heap of edges from the root (from each component's first node too with 'forest'); ties go to the edge listed first.
maxflow:
    Python: graphs.py. Edmonds and Karp's method: shortest augmenting paths found breadth first in the residual graph (neighbours by number) until none is left; the minimum cut's side cs is what s still reaches.
centrality:
    Python: graphs.py. Degrees summed over edges; closeness from the distances of each node; betweenness by Brandes' method (breadth first, or Dijkstra with weights), halved for a graph; pagerank by power iteration with dangling nodes spread evenly, until the change's sum is below n times the tolerance; eigenvector, hubs and authorities from numpy.linalg.eigh of A, A*A' and A'*A, the leading vector's magnitudes made to sum to 1.
isisomorphic:
    Python: graphs.py. A backtracking search matching nodes of equal in- and out-degrees, each match checked against those made before.
highlight, labelnode, labeledge, layout:
    Python: graphs.py. The GraphPlot keeps its own colours, sizes and labels for nodes and edges and draws again as line, scatter, patch (arrowheads) and text objects in the axes. Layouts: 'circle' from the top going clockwise; 'layered' by the longest path into each node (cycles broken depth first), each layer's nodes ordered by where the nodes above them are; 'force' Fruchterman and Reingold's spring model from the circle, 100 steps with cooling; 'subspace' the Laplacian's eigenvectors 2 and 3 (numpy.linalg.eigh).
# ---- unittests.py and pycall.py: unit tests, calling Python --------------------------------------------------------------------------
runtests, testsuite, matlab.unittest.TestSuite.fromFile, matlab.unittest.TestSuite.fromFolder, matlab.unittest.TestSuite.fromName, matlab.unittest.TestSuite.fromClass:
    Python: unittests.py. PyLAB's own runner. A test class's Test methods are found by their methods block attributes (its superclasses' too), TestParameter properties expanded with itertools.product; a function file is run for its functiontests; a script is cut at its %% lines. Each test of a class gets a copy of the object the TestClassSetup methods worked on; each is timed with time.perf_counter. Names and patterns are matched with fnmatch.
functiontests, localfunctions:
    Python: unittests.py. localfunctions walks Python's stack to the compiled file it is called from and makes a handle for each of its functions after the first; functiontests sorts them into tests and fixtures by name.
matlab.unittest.TestCase.forInteractiveUse, matlab.unittest.TestRunner.withTextOutput, matlab.unittest.TestRunner.withNoPlugins, assertSuccess, addTeardown:
    Python: unittests.py. A test case of PyLAB's own for the prompt; a runner that keeps how much it reports; the teardowns kept with the running test and called last first.
pyrun, pyrunfile, pyenv, pyargs:
    Python: pycall.py. Python's exec in a dict kept as __main__ (pyrun) or a new one (pyrunfile, with sys.argv set), sys.stdout and sys.stderr sent to the Command Window while it runs, a Python exception made an error that names it. py.a.b names are found by importlib.import_module and getattr (Python's builtins module first), values converted both ways by PyLAB's own rules.
# ---- odemore.py: boundary value problems, delays, PDEs, the ode object -------------------------------------------------------------------
bvp4c:
    Python: odemore.py. SciPy's scipy.integrate.solve_bvp: cubic pieces, continuous with their first derivatives, collocated at each interval's ends and midpoint (the three-stage Lobatto IIIA formula, fourth order), Newton's method on the collocation equations, the mesh refined where the rms residual, relative to 1 + |f|, exceeds RelTol. A FJacobian is passed to it; SingularTerm is its S.
bvp5c:
    Python: odemore.py. PyLAB's own: the four-stage Lobatto IIIA collocation (c = 0, (5 -+ sqrt(5))/10, 1; its coefficients the integrals of the Lagrange polynomials), the node and stage values solved together by damped Newton steps on a SciPy sparse Jacobian (by differences, block by block), then the rms residual of the quartic on each interval, by three-point Gauss quadrature relative to 1 + |f|, against RelTol; an interval over it is split in two (in three when it is over 100 times), until all pass or NMax.
bvpinit, bvpxtend, bvpset, bvpget:
    Python: odemore.py. Structs as the solvers read them.
dde23, ddesd:
    Python: odemore.py. PyLAB's own method of steps: the Bogacki-Shampine 3(2) pair with the error per step against AbsTol + RelTol |y|, the delayed values from cubic Hermite interpolation of the steps taken (the history before the start); when a delay is shorter than the step, the step is done again with the delayed values from its own interpolant until it settles. dde23 also steps to t0 plus sums of up to three lags. Events are found by Brent's method (scipy.optimize.brentq) on the step's interpolant.
ddeset, ddeget:
    Python: odemore.py. Structs as the solvers read them.
pdepe:
    Python: odemore.py. PyLAB's own method of lines: each node's equation integrated over its cell (from the midpoints on each side, weighted by x^m, exactly), c, f and s at the midpoints of the mesh's intervals with u their mean and du/dx their slope; at an end, the flux from the boundary condition, or u held there when q is 0. The equations M(t, u) u' = F(t, u), M diagonal (zero for elliptic rows), are solved by ode15s (odesolvers.NDF) with a Jacobian by differences, columns three nodes apart at once.
pdeval:
    Python: odemore.py. Linear interpolation between the mesh points.
ode, solutionFcn:
    Python: odemore.py. An object of PyLAB's own whose properties become the arguments and odeset options of the solver it selects; solutionFcn keeps that solver's dense output (sol.idata) behind a function handle.
# ---- mlunsup.py, mlmodels.py, learners.py: statistics and machine learning ---------------------------------------------------
pdist, pdist2, squareform, knnsearch, rangesearch:
    Python: mlunsup.py. SciPy's scipy.spatial.distance (pdist, cdist, squareform) with the language's names for the metrics ('spearman' the correlation of the rows' ranks by scipy.stats.rankdata); neighbours by sorting the distances (numpy.argsort, stable).
kmeans, kmedoids:
    Python: mlunsup.py. PyLAB's own: k-means++ seeding from rng's generator, then Lloyd's batch iterations (kmeans); for kmedoids the Voronoi iteration and then single swaps while they lower the total distance.
linkage, cluster, clusterdata, cophenet, inconsistent, optimalleaforder, dendrogram:
    Python: mlunsup.py. SciPy's scipy.cluster.hierarchy (linkage, fcluster, cophenet, inconsistent, optimal_leaf_ordering, dendrogram's coordinates), the leaves numbered from 1 and the clusters renumbered by their first observation; the dendrogram drawn as line objects.
dbscan, spectralcluster, silhouette, evalclusters:
    Python: mlunsup.py. PyLAB's own: DBSCAN by a depth-first expansion from each core point; spectral clustering by scipy.linalg.eigh of the graph Laplacian (generalized with the degrees for 'randomwalk') and kmeans of the eigenvectors; silhouettes and the Calinski-Harabasz, Davies-Bouldin and gap criteria from their definitions.
gmdistribution, fitgmdist, posterior, mahal:
    Python: mlunsup.py. EM written here (responsibilities by scipy.stats.multivariate_normal.logpdf, log-sum-exp), from k-means++ starts; mahal by a QR factorization of the centred sample.
pca, pcacov, ppca:
    Python: mlunsup.py. numpy.linalg.svd of the centred (weighted) data; ppca by EM (Tipping and Bishop), each row's posterior from its observed entries.
factoran, rotatefactors:
    Python: mlunsup.py. The likelihood as a function of the specific variances (the loadings from the eigenvectors of the scaled correlations, Joreskog's method), minimized by scipy.optimize.minimize (L-BFGS-B, psi in [Delta, 1]); orthomax rotations by the SVD iteration, promax by a least-squares fit to the powered varimax loadings.
cmdscale, mdscale, tsne, procrustes, canoncorr, barttest, nnmf, corrcov:
    Python: mlunsup.py. cmdscale by numpy.linalg.eigh of the doubly centred squared distances; mdscale by L-BFGS on each criterion with its gradient (nonmetric: alternating with isotonic regression by pool-adjacent-violators); exact t-SNE (van der Maaten's gradient descent with momentum and gains); procrustes and canoncorr by the SVD (canoncorr of the QR factors); barttest from the covariance's eigenvalues; corrcov divides by sigma*sigma', cuts round-off past 1 back to 1 and puts sign(diag) on the diagonal; nnmf by alternating nonnegative least squares or Lee and Seung's multiplicative updates.
fitctree, fitrtree, view:
    Python: learners.py and mlmodels.py. PyLAB's own CART: each candidate split of each variable scored at once from cumulative class counts (or sums and sums of squares), the nodes split breadth first.
fitcknn, fitcdiscr, fitcnb:
    Python: learners.py. Distances by scipy.spatial.distance.cdist; discriminant and naive Bayes posteriors from their log densities (numpy.linalg.pinv and slogdet, scipy.stats.norm), normalized by log-sum-exp.
fitcsvm, fitrsvm:
    Python: learners.py. PyLAB's own SMO with LIBSVM's second-order choice of the pair (Fan, Chen and Lin), on the precomputed kernel matrix; regression as LIBSVM poses it, with 2n variables.
fitcecoc, templateTree, templateSVM, templateKNN, templateDiscriminant, templateNaiveBayes, templateLinear, templateKernel, templateGP:
    Python: mlmodels.py. A binary learner for each column of the coding matrix on the classes it names, decoded by the mean binary loss.
fitcensemble, fitrensemble, TreeBagger, oobLoss, oobPredict:
    Python: mlmodels.py. Bagging (bootstrap samples from rng's generator, random variables at each split), AdaBoost.M1, SAMME, GentleBoost, LogitBoost and least-squares boosting, written here over learners.py's trees.
fitclinear, fitrlinear, fitckernel, fitrkernel:
    Python: learners.py. Logistic and least squares by scipy.optimize.minimize (L-BFGS-B; lasso by splitting the coefficients into positive parts); linear SVMs by dual coordinate descent (Hsieh and others; Ho and Lin for regression), the bias as a constant column; random Fourier features (Rahimi and Recht) from rng's generator.
fitcnet, fitrnet:
    Python: learners.py. A multilayer perceptron in NumPy, its gradient by backpropagation, minimized by scipy.optimize.minimize (L-BFGS-B).
fitrgp:
    Python: learners.py. The exact marginal likelihood by a Cholesky factorization (numpy.linalg.cholesky), its gradient analytic, minimized by L-BFGS-B over the logarithms of the parameters from the given (or default) start and from noise a tenth and a hundredth of it; the best is kept.
loss, resubLoss, resubPredict, compact, crossval, kfoldLoss, kfoldPredict, cvpartition, training, test, repartition:
    Python: mlmodels.py. Losses from the scores as the help gives them; cross-validation by fitting again with the same options on each training set; partitions by permutations from rng's generator (stratified within each group).
confusionmat, confusionchart, perfcurve:
    Python: mlmodels.py. Counts by class; the chart drawn as patches and text; perfcurve's criteria counted at each distinct score, its area by the trapezoid rule.
# ---- statsmore.py: more statistics ---------------------------------------------------------------------------------------------------
lasso:
    Python: statsmore.py. PyLAB's own cyclic coordinate descent with soft thresholding (as Friedman, Hastie and Tibshirani's glmnet), warm started from each lambda to the next; cross-validation by refitting on each training set.
stepwiselm:
    Python: statsmore.py. Each candidate model fitted by numpy.linalg.lstsq, the partial F statistics compared with scipy.stats.f; the final model is fitlm's.
anovan:
    Python: statsmore.py. Effect-coded design matrices; each sum of squares the difference of residual sums of squares of nested least-squares fits (numpy.linalg.lstsq), the degrees of freedom the difference of their ranks.
manova1:
    Python: statsmore.py. The generalized eigenproblem of B and W (scipy.linalg.eigh); Bartlett's chi-square on the product of 1/(1 + eigenvalue).
bootci:
    Python: statsmore.py. Resamples drawn by rng's generator; percentiles by numpy.percentile; BCa's acceleration from the jackknife (Efron and Tibshirani).
ansaribradley:
    Python: statsmore.py. SciPy's scipy.stats.ansari for the p-value; W and its normal score from the rank scores.
copularnd, copulapdf, copulacdf, copulastat, copulaparam, copulafit:
    Python: statsmore.py. Gaussian and t by their multivariate distributions (scipy.stats); Clayton by the gamma frailty (Marshall and Olkin), Gumbel by a positive stable frailty (Chambers, Mallows and Stuck), Frank by inverting its conditional distribution; Frank's tau by quadrature of Debye's function; fits by scipy.optimize.minimize_scalar.
fullfact, ff2n, fracfact, bbdesign, ccdesign, candgen:
    Python: statsmore.py. The designs built from itertools.product of the levels.
candexch, rowexch:
    Python: statsmore.py. Fedorov's exchange: the swap that most increases det(X'X), by the variance function from its inverse, until none does; the best of the random starts kept.
hmmgenerate, hmmviterbi, hmmdecode, hmmestimate, hmmtrain:
    Python: statsmore.py. Scaled forward-backward recursions, Viterbi in logarithms, Baum-Welch expected counts; the process in state 1 before the first step; draws from rng's generator.
coxphfit:
    Python: statsmore.py. Newton's method with step halving on the log partial likelihood, its gradient and Hessian summed over the failure times (Breslow's or Efron's handling of ties).
relieff, fscchi2, fscmrmr, sequentialfs:
    Python: statsmore.py. ReliefF (Kononenko; Robnik-Sikonja and Kononenko for regression) on range-scaled Manhattan distances; chi-square tests by scipy.stats.chi2_contingency; mutual information from contingency tables; sequential selection with cvpartition's folds.
andrewsplot, parallelcoords, probplot:
    Python: statsmore.py. Line objects; probplot's quantiles by scipy.stats.
# ---- control.py: control systems -----------------------------------------------------------------------------------------------------------
tf, zpk, ss, pid, feedback, parallel, tfdata, zpkdata, ssdata:
    Python: control.py. A model object of PyLAB's own keeping the form it was made in (numpy polynomial rows, roots and gains, or matrices). Products and sums of single-input single-output transfer functions by numpy.polymul; otherwise state-space interconnection formulas (block-diagonal, series and feedback realizations). Conversions: scipy.signal.tf2ss and ss2tf (after removing the states an input cannot reach or an output cannot see), numpy.roots and poly.
ss2tf, tf2ss:
    Python: control.py. SciPy's scipy.signal.ss2tf and tf2ss.
pole, zero, tzero, dcgain, evalfr, freqresp, damp, isstable:
    Python: control.py. numpy.linalg.eigvals of A (of a minimal realization), numpy.roots, scipy.linalg.eigvals of the system pencil; responses by solving (sI - A) x = B at each frequency, or by evaluating the polynomials.
ctrb, obsv, gram, covar, lyap, dlyap, care, dare:
    Python: control.py. SciPy's scipy.linalg solve_continuous_lyapunov, solve_discrete_lyapunov, solve_sylvester, solve_continuous_are and solve_discrete_are.
lqr, dlqr, lqry, lqe, kalman, estim, reg, place, acker:
    Python: control.py. Gains from the Riccati solutions; place by scipy.signal.place_poles; acker by Ackermann's formula with the controllability matrix.
getPeakGain, hinfnorm:
    Python: control.py. The largest singular value on 2000 frequencies about the poles and zeros, each local peak refined by scipy.optimize.minimize_scalar (bounded).
c2d, d2c, pade:
    Python: control.py. scipy.signal.cont2discrete ('zoh', 'foh', 'bilinear', 'impulse'); 'matched' by mapping roots; d2c by scipy.linalg.logm or the inverse bilinear formulas; Pade coefficients (2N - k)! N!/((2N)! k! (N - k)!).
minreal, ss2ss, xperm, canon, hsvd, balreal, balred, modred:
    Python: control.py. Minimal realizations by SVDs of the controllability and observability matrices; balancing by the square-root method (Cholesky factors of the Gramians, an SVD); reduction by truncation or singular perturbation.
step, impulse, initial, stepplot, impulseplot, lsim, stepinfo:
    Python: control.py. Each step exact for a piecewise-linear (or constant) input by scipy.linalg.expm of the augmented matrix; discrete models by their recurrence.
bode, bodeplot, nyquist, nichols, sigma:
    Python: control.py. The response on 400 logarithmically spaced frequencies two decades beyond the poles and zeros (to the Nyquist frequency in discrete time); phases by numpy.unwrap.
margin, allmargin:
    Python: control.py. The crossings of the negative real axis (sign changes of Im H with Re H < 0) and of |H| = 1 on 6000 frequencies, each refined by scipy.optimize.brentq.
rlocus, pzmap:
    Python: control.py. numpy.roots of den + k num on 600 gains spaced logarithmically, each root joined to the nearest one at the gain before.
# ---- globalopt.py: global optimization -----------------------------------------------------------------------------------------------------
ga, gamultiobj:
    Python: globalopt.py. PyLAB's own genetic algorithms in NumPy (rank scaling, stochastic uniform selection, scattered crossover, Gaussian mutation; gamultiobj with nondominated sorting and crowding distances), drawing from rng's generator.
particleswarm:
    Python: globalopt.py. PyLAB's own particle swarm with random neighbourhoods and adaptive inertia.
simulannealbnd:
    Python: globalopt.py. PyLAB's own annealing: exponential cooling, steps of the temperature's length, the logistic acceptance rule.
patternsearch:
    Python: globalopt.py. PyLAB's own generalized pattern search on the positive basis of 2n coordinate directions; constraints by the augmented Lagrangian.
surrogateopt:
    Python: globalopt.py. Cubic radial basis interpolation with a linear tail by numpy.linalg.lstsq; candidates scored by a weighted sum of the surrogate and the distance to the points evaluated.
createOptimProblem, MultiStart, GlobalSearch:
    Python: globalopt.py. The local solver (fmincon, fminunc, lsqnonlin, lsqcurvefit or fminsearch) called from each start point; solutions merged when within the tolerances.
# ---- wavelets.py ---------------------------------------------------------------------------------------------------------------------------------
wfilters, dbwavf, symwavf, coifwavf, orthfilt, biorfilt, qmf:
    Python: wavelets.py. Filters computed in decimal arithmetic (the standard library's decimal, 60 digits): Weierstrass' iteration for the roots of the Daubechies polynomial, Newton's method for the coiflets, fractions for the spline biorthogonal ones.
dwt, idwt, wavedec, waverec, appcoef, detcoef, wrcoef, upcoef, wenergy, dwt2, idwt2, wavedec2, waverec2, appcoef2, detcoef2, wrcoef2, dwtmode, wmaxlev:
    Python: wavelets.py. NumPy: the extended signal sliced by twos, tap by tap; two dimensions as rows then columns.
swt, iswt, swt2, iswt2:
    Python: wavelets.py. NumPy: circular filtering with the upsampled filters.
modwt, imodwt, modwtmra:
    Python: wavelets.py. numpy.fft: the filters' transforms at 2^(j-1) times each frequency.
wavefun, centfrq, scal2frq:
    Python: wavelets.py. The cascade algorithm in NumPy; numpy.fft for the centre frequency.
cwt, icwt, cwtfreqbounds:
    Python: wavelets.py. numpy.fft with the wavelets' spectra; scipy.optimize.brentq for the cutoff, scipy.integrate.quad for the admissibility constant.
wthresh, wnoisest, thselect, wden, ddencmp, wdenoise, wcodemat:
    Python: wavelets.py. NumPy; scipy.special (ndtr, ndtri, erfcx) for the empirical Bayes rule, written to avoid overflow.
metaclass, meta.class.fromName:
    Python: langmore.py. The class's description read from the compiled class (classdef.py's ClassInfo: its properties with their attributes and defaults, methods, events, enumeration members and superclasses), the lists made when first read; one meta.class object for each class, so == compares them; < and <= ask whether one class is among the other's superclasses. ?Name is parsed as meta.class.fromName('Name').
subsref, subsasgn, substruct:
    Python: langmore.py. The steps of the struct array run through the engine's own indexing (index.py's idx, cidx and fld for subsref; asgn_chain, which a chained assignment uses, for subsasgn); substruct checks the types and makes the struct.
namedargs2cell, isStringScalar:
    Python: langmore.py. The struct's fields walked in order into a cell row; a string array of one element.
matlab.net.base64encode, matlab.net.base64decode:
    Python: langmore.py. Python's base64.b64encode and base64.b64decode (strict, padding added), text as UTF-8 bytes.
unicode2native, native2unicode:
    Python: langmore.py. Python's str.encode and bytes.decode with the codec named (codecs.lookup), unknown characters replaced.
textwrap:
    Python: langmore.py. Words (split at white space) added to a line while it stays within the width, a longer word cut into pieces of the width.
isMATLABReleaseOlderThan, verLessThan:
    Python: langmore.py. The release or version checked for its form, then false.
calendar:
    Python: langmore.py. Python's calendar.monthrange for the first weekday and the number of days, laid out from Sunday.
array2timetable:
    Python: langmore.py. Each column taken by indexing and passed with the options to timetable (tables.py).
fileattrib, recycle:
    Python: langmore.py. os.stat's mode bits for the permissions and os.chmod to change them (glob for a *); recycle keeps 'on' or 'off' only.
gtext:
    Python: langmore.py. ginput(1) for the click, then text at that point.
uniquetol, ismembertol:
    Python: numerics.py. The values sorted (numpy.argsort, stable); uniquetol walks them, starting a group whenever a value is more than tol*DataScale from the group's first; ismembertol finds the values of B within reach of each value of A by numpy.searchsorted on B sorted. By rows, every pair of rows is compared column by column.
lsqminnorm:
    Python: numerics.py. scipy.linalg.qr with pivoting gives A*P = Q*R; the rank is the number of |R(k,k)| above tol; the leading rows of R are factored again by numpy.linalg.qr of their transpose (R1' = Z*T), and X = P*Z*inv(T')*Q1'*B by triangular solves (scipy.linalg.solve_triangular): a complete orthogonal decomposition. A regularization factor appends lambda*I to A and zeros to B.
decomposition, isIllConditioned:
    Python: numerics.py. The factorization made once by SciPy: scipy.linalg.lu_factor (lu, banded), scipy.linalg.cho_factor (chol), scipy.linalg.ldl (ldl: L*D*L' solved by two triangular solves about D), scipy.linalg.qr or the complete orthogonal decomposition of lsqminnorm (qr, cod); triangular and diagonal matrices are solved directly. \ and / come through the operators (ops.py's OBJ_OPS); b/dA is (dA'\b')'. rcond is 1/(norm(A,1)*norm(inv(A),1)).
sylvester:
    Python: numerics.py. scipy.linalg.solve_sylvester (Bartels-Stewart through the Schur forms).
lscov:
    Python: numerics.py. The rows scaled by sqrt(w), or both sides multiplied by the inverse Cholesky factor of V (numpy.linalg.cholesky, scipy.linalg.solve_triangular), then least squares by scipy.linalg.qr with pivoting; S from the inverse of R on the pivot columns.
normest1:
    Python: numerics.py. scipy.sparse.linalg.onenormest (Higham and Tisseur's block algorithm), or the exact largest column sum for small matrices.
subspace:
    Python: numerics.py. Orthonormal bases by scipy.linalg.orth; the part of the smaller one outside the larger, its 2-norm s, and asin(min(1, s)).
condeig:
    Python: numerics.py. eig's V and D; the rows of numpy.linalg.inv(V) are the left eigenvectors scaled so that w'*v = 1, so each condition number is the product of the norms.
cdf2rdf:
    Python: numerics.py. The diagonal walked; a complex eigenvalue and its conjugate next to it become a 2-by-2 block of the real and imaginary parts, their vectors the real and imaginary parts of the first.
hadamard:
    Python: numerics.py. The 12-by-12 one from a Toeplitz matrix (scipy.linalg.toeplitz) and the 20-by-20 one from a Hankel matrix (scipy.linalg.hankel) of 1 and -1, each bordered by ones, then Sylvester's doubling [H H; H -H].
delaunayn, convhulln, griddatan:
    Python: numerics.py. scipy.spatial.Delaunay and scipy.spatial.ConvexHull (Qhull); griddatan finds each query's simplex (Delaunay.find_simplex), its barycentric coordinates from Delaunay.transform weighting the values at the corners, or the nearest point by scipy.spatial.cKDTree.
nufft, nufftn:
    Python: numerics.py. The sums written as products with matrices of numpy.exp(-2j*pi*f*t), a block of frequencies at a time to bound the memory.
colperm, symbfact:
    Python: numerics.py. colperm sorts the column counts (numpy.argsort, stable). symbfact builds the factor's structure column by column: column j holds the rows of A's pattern below the diagonal and those of its children in the elimination tree; its parent is its first row below the diagonal; the counts, a postorder and the height follow.
rmse, mape:
    Python: numerics.py. abs(F - A).^2 (or abs((A - F)./A)) passed to mean with the same dimensions, flags and weights, then the square root (or times 100).
triangulation, delaunayTriangulation:
    Python: geomclasses.py. The points and simplices kept as arrays; a Delaunay triangulation by scipy.spatial.Delaunay (Qhull with 'Qt Qbb Qc Qz'), its triangles turned counterclockwise and put in a fixed order; duplicates found by numpy.unique.
pointLocation, cartesianToBarycentric, barycentricToCartesian:
    Python: geomclasses.py. For every simplex the inverse of its edge matrix (numpy.linalg.inv), the barycentric coordinates of each point in each simplex at once (numpy.einsum), the first simplex where none is negative; cartesianToBarycentric by numpy.linalg.lstsq with the coordinates summing to one.
nearestNeighbor:
    Python: geomclasses.py. scipy.spatial.cKDTree of the vertices.
edges, neighbors, vertexAttachments, edgeAttachments, isConnected, freeBoundary, featureEdges:
    Python: geomclasses.py. The simplices' facets sorted and matched (a dictionary of facets) for the neighbours and for the facets used once; in 2-D those boundary edges chained head to tail. Attachments are the rows holding the vertices; featureEdges compares the normals of the two triangles at each edge.
circumcenter, incenter:
    Python: geomclasses.py. The circumcentre solves the Gram system of the edge vectors (numpy.linalg.solve); the incentre weights the vertices by the opposite sides' lengths (faces' areas), the radius 2A/perimeter (3V/surface).
faceNormal, vertexNormal:
    Python: geomclasses.py. numpy.cross of two edges, made unit; at a vertex the sum of its triangles' unit normals (numpy.add.at), made unit.
convexHull, voronoiDiagram, isInterior:
    Python: geomclasses.py. scipy.spatial.ConvexHull and scipy.spatial.Voronoi (its point at infinity moved to the first row); isInterior reports that constrained edges are not supported.
alphaShape, alphaSpectrum, criticalAlpha, alphaTriangulation, boundaryFacets, inShape, numRegions, surfaceArea, volume:
    Python: geomclasses.py. The Delaunay simplices (scipy.spatial.Delaunay) with their circumradii; those up to Alpha kept, joined into regions through shared facets (a walk over neighbours), regions under RegionThreshold dropped and enclosed groups of left-out simplices under HoleThreshold filled. The critical alphas: for 'all-points' the largest over points of the smallest radius at each point, for 'one-region' the first radius from there that leaves one region. Areas and volumes sum the simplices'; the boundary is the facets used once.
boundary:
    Python: geomclasses.py. An alpha shape with every hole filled; alpha taken from its spectrum between criticalAlpha 'one-region' (s = 1) and the largest radius (s = 0); in 2-D the boundary edges chained into one loop. For a polyshape (polyshapes.py), its rings closed and parted by NaN.
polyshape, nsidedpoly, centroid, perimeter, boundingbox, numboundaries, numsides, ishole, issimplified, isinterior, nearestvertex, overlaps, regions, holes, addboundary, rmboundary, rmholes, rmslivers, scale, translate, sortboundaries, sortregions, subtract, polybuffer:
    Python: polyshapes.py. The boundaries kept as rings; the geometry built in Shapely (GEOS): rings combined even-odd for nesting (symmetric_difference) or solids less holes, mended by make_valid, oriented with shapely.geometry.polygon.orient (solids clockwise) and simplified (collinear vertices dropped) by simplify(g, 0). Booleans are Shapely's union, intersection, difference and symmetric_difference; polybuffer its buffer (round, mitre with a limit, or mitre at 1 for square corners); rmslivers a buffer in and out; isinterior contains and the distance to the rings; measures from the rings (the shoelace area) or Shapely's centroid.
nccreate, ncwrite, ncread, ncinfo, ncdisp, ncreadatt, ncwriteatt:
    Python: netcdf.py. The kind read from the file's first bytes: classic (CDF-1) and 64-bit (CDF-2) files through scipy.io.netcdf_file, netCDF-4 files through h5py by the netCDF-4 conventions (each dimension a dimension scale, a placeholder dataset named for a dimension without a variable, _Netcdf4Dimid, _nc3_strict for the classic model, variables attached to their dimensions, creation order kept). Arrays are transposed between the language's order and the file's; scale_factor, add_offset, _FillValue and missing_value applied on reading and reversed on writing; unlimited dimensions resized as data arrive.
rectangle:
    Python: graphics_base.py. A patch (Rectangle) whose outline is worked out from Position and Curvature: quarter ellipses of radii cx*w/2 and cy*h/2 at the corners, 17 points each.
hggroup, hgtransform, makehgtform:
    Python: graphics_base.py. Groups hold children; when the axes are drawn (and their limits worked out) the groups are opened in place and their children's data multiplied by the matrices of the transforms above them, on copies. makehgtform (plotmore.py) multiplies translation, scaling and rotation matrices (Rodrigues' formula) in order.
rotate:
    Python: plotmore.py. A rotation matrix about the unit direction (Rodrigues' formula) applied to the data less the origin; for a polyshape (polyshapes.py) a 2-D rotation of its rings.
refreshdata:
    Python: plotmore.py. Each data source compiled as an assignment in the workspace (runtime.py's compile_command) and run, its value set as the data.
xtickformat, ytickformat, ztickformat, ztickangle:
    Python: plotmore.py. The format kept with the axes and sent to the page, which writes each tick with a printf-like formatter of its own (pylab-figure.js), commas grouping thousands; glayout.py's format_tick does the same for get.
rticks, thetaticks, rticklabels, thetaticklabels, rlim:
    Python: plotmore.py. The polar axes' RTick, ThetaTick, RTickLabel, ThetaTickLabel and RLim set (manual) or given back (auto, as glayout.py's polar_ticks works them out); the page draws the rings and spokes from them, turned by ThetaDir and ThetaZeroLocation.
gplot, treelayout, treeplot, etreeplot:
    Python: plotmore.py. gplot joins the rows of xy for each nonzero pair, NaN between edges. treelayout walks each tree depth first, numbering the leaves across and centring each parent over its children; treeplot draws that with plot; etreeplot takes etree of A + A'.
validatecolor, rgb2hex, hex2rgb:
    Python: plotmore.py. Colour names and codes read as the graphics read them (graphics_base.py's to_color); integers scaled by their range; hex digits written and read two to a channel.
brighten, rgbplot, spinmap:
    Python: plotmore.py. The colormap's values raised to the power 1 - beta or 1/(1 + beta) (numpy.clip first); three plot lines; numpy.roll of the colormap's rows, set again between pauses.
surfnorm:
    Python: plotmore.py. Tangents by numpy.gradient along the columns and rows, numpy.cross of them made unit.
shrinkfaces:
    Python: plotmore.py. Each face's vertices moved towards its centroid by sqrt(sf), on vertices of its own.
isocolors:
    Python: plotmore.py. scipy.interpolate.RegularGridInterpolator (linear) over the volume's grid at the vertices.
lightangle:
    Python: plotmore.py. The light's Position [sin(az)cos(el), -cos(az)cos(el), sin(el)], and back by atan2 and asin.
adapthisteq:
    Python: imagemore.py. The image padded (mirrored) to whole tiles; each tile's histogram (numpy.bincount) clipped with the excess spread evenly, its cumulative sum the tile's mapping; every pixel's value from the four nearest tiles' mappings, weighted bilinearly by the distance to their centres.
imhistmatch, otsuthresh, multithresh, imquantize, im2bw:
    Python: imagemore.py. imhistmatch maps each pixel's rank to the reference's cumulative histogram (numpy.searchsorted). otsuthresh and multithresh maximize the between-class variance; multithresh by dynamic programming over the 256 bins with cumulative sums, exactly. imquantize counts the levels below each value (numpy.searchsorted).
imgradientxy, imgradient:
    Python: imagemore.py. The Sobel or Prewitt kernels correlated with the image (imageproc.py's _correlate, the border replicated), or numpy.gradient and numpy.diff; the magnitude numpy.hypot and the direction numpy.arctan2 of -Gy and Gx.
bwlabeln, bwareaopen, bwareafilt, bwpropfilt, bwselect:
    Python: imagemore.py. Components by scipy.ndimage.label (renumbered by their first pixel down the columns), their sizes by numpy.bincount; bwpropfilt asks regionprops for the property.
bwperim, bweuler, bwarea:
    Python: imagemore.py. bwperim keeps on pixels with a neighbour off (the image moved one pixel each way); bweuler counts objects and the background's enclosed parts with scipy.ndimage.label; bwarea weights each 2-by-2 pattern.
bwdist:
    Python: imagemore.py. scipy.ndimage.distance_transform_edt and scipy.ndimage.distance_transform_cdt with the nearest pixels' indices; 'quasi-euclidean' by two raster passes with steps of 1 and sqrt(2).
bwskel, bwconvhull, bwtraceboundary:
    Python: imagemore.py. bwskel is bwmorph's thinning (Zhang and Suen) repeated until nothing changes, branches pruned by walking from their end points; bwconvhull takes scipy.spatial.ConvexHull of the pixels' corners and keeps the pixels whose centres lie inside; bwtraceboundary is bwboundaries' Moore tracer, turned to start at the pixel given.
imreconstruct, imregionalmax, imregionalmin, imhmax, imhmin, imextendedmax, imextendedmin, imimposemin, imclearborder:
    Python: imagemore.py. Reconstruction by dilation repeated (the image moved one pixel each way, the larger kept, then the smaller with the mask) until it stops changing; for binary images the mask's components touching the marker (scipy.ndimage.label). Regional maxima are where I less the reconstruction of I - h (h smaller than any difference of values) stays above h/2; the minima, the extended and h-extrema, imposed minima (a reconstruction by erosion) and clearing the border all follow from it.
watershed:
    Python: imagemore.py. Meyer's flooding: the regional minima labelled, then a priority queue (heapq) of pixels by value; each pixel taken gets the label of its labelled neighbours if they share one, else 0 (a ridge).
imtophat, imbothat:
    Python: imagemore.py. imopen and imclose (imageproc.py) less or from the image.
label2rgb, labeloverlay, imoverlay:
    Python: imagemore.py. A table of colours (colormaps.py, the zero colour first) indexed by the labels; labeloverlay blends with the image by Transparency.
rgb2lab, lab2rgb, rgb2xyz, xyz2rgb, rgb2ycbcr, ycbcr2rgb, im2int16:
    Python: imagemore.py. sRGB's companding undone and the matrix of its primaries and D65 white (Adobe RGB's, or none for linear RGB), then CIE L*a*b*'s cube-root function with the white point; Y'CbCr by the BT.601 matrix and offsets; back by numpy.linalg.inv of the matrices.
imadd, imsubtract, immultiply, imdivide, imabsdiff, imlincomb:
    Python: imagemore.py. Computed in double with NumPy, then rounded and saturated into the class.
imnoise:
    Python: imagemore.py. rng's generator (elmat.py's RNG): normal and uniform numbers, numpy.random.RandomState.poisson for 'poisson'.
imsharpen:
    Python: imagemore.py. scipy.ndimage.gaussian_filter for the blur; RGB through rgb2lab and lab2rgb.
imfuse, imshowpair:
    Python: imagemore.py. The images made gray (rgb2gray's weights), set on one canvas, scaled, and put in the colour channels, blended, differenced or interleaved.
corr2, immse, psnr, ssim, entropy:
    Python: imagemore.py. NumPy sums; ssim's local statistics by scipy.ndimage.gaussian_filter (mode 'nearest'); entropy from numpy.bincount of the uint8 image.
entropyfilt, stdfilt, rangefilt, imboxfilt, integralImage:
    Python: imagemore.py. Local sums by scipy.ndimage.correlate (of each grey level's indicator for entropyfilt) and scipy.ndimage.uniform_filter; rangefilt from imageproc.py's flat dilation and erosion; numpy.cumsum for the integral image.
imguidedfilter, imbilatfilt, imdiffusefilt, imgaussfilt3, ordfilt2, wiener2:
    Python: imagemore.py. The guided filter from box means (scipy.ndimage.uniform_filter); the bilateral filter summed over the neighbourhood's offsets; diffusion stepped explicitly; scipy.ndimage.gaussian_filter in 3-D; scipy.ndimage.rank_filter with the domain as footprint; wiener2 from local means by scipy.ndimage.correlate.
psf2otf, otf2psf, deconvwnr, deconvlucy:
    Python: imagemore.py. numpy.fft.fftn of the PSF padded and rolled to its centre; the deconvolutions by products of spectra (numpy.fft.fft2, numpy.fft.ifft2).
padarray, im2col, col2im:
    Python: imagemore.py. numpy.pad ('wrap', 'edge', 'symmetric' or a constant); blocks sliced and reshaped in column order.
blockproc, nlfilter, colfilt:
    Python: imagemore.py. The blocks sliced from the padded image and passed to the function (its own call, awaited); colfilt passes them all at once as im2col's columns.
impyramid, improfile, imcontour:
    Python: imagemore.py. scipy.ndimage.correlate1d with the 5-tap kernel; improfile samples the path through imageproc.py's interpolation; imcontour is contour with axis ij and image.
affine2d, projective2d, affinetform2d, projtform2d, rigidtform2d, simtform2d, transltform2d, transformPointsForward, transformPointsInverse, invert, outputLimits, isTranslation, isRigid, isSimilarity:
    Python: imgeom.py. Each kept as a 3-by-3 matrix for column vectors (a legacy object's T is its transpose); points through it in homogeneous coordinates, back through numpy.linalg.inv; outputLimits transforms the rectangle's edges.
imref2d, worldToIntrinsic, intrinsicToWorld, worldToSubscript, sizesMatch:
    Python: imgeom.py. The world limits and size, the pixel extents their quotient; conversions are linear.
imwarp:
    Python: imgeom.py. The output grid's pixel centres taken to world coordinates, back through the inverse transformation, to the input's intrinsic coordinates, and sampled there (imageproc.py's interpolation).
fitgeotrans, fitgeotform2d:
    Python: imgeom.py. Affine by numpy.linalg.lstsq; similarity and rigid in closed form from the SVD of the cross-covariance (Umeyama); projective by the direct linear transform on normalized points (numpy.linalg.svd).
imregcorr:
    Python: imgeom.py. Phase correlation: the normalized cross-power spectrum (numpy.fft.fft2), its inverse's peak refined by parabolas. For rotation and scale the magnitude spectra are high-passed and resampled to log-polar coordinates, whose phase correlation gives the angle and the log of the scale; then the translation, trying the angle and the angle + 180 degrees.
hough, houghpeaks, houghlines:
    Python: imgeom.py. Votes added by numpy.add.at for each angle; peaks found and their neighbourhoods cleared in turn; lines from the pixels within half a rho step of each peak's line, sorted along it and split at gaps.
imfindcircles:
    Python: imgeom.py. Sobel gradients (scipy.ndimage.correlate), votes along the gradient by numpy.add.at at each radius, smoothed by scipy.ndimage.gaussian_filter; local maxima (scipy.ndimage.maximum_filter) checked by a histogram of the voting pixels' distances and by the edge pixels round the circle.
radon, iradon, phantom:
    Python: imgeom.py. radon bins four subpixels per pixel by numpy.add.at; iradon filters each projection (numpy.fft.fft; the ramp built in space and transformed, after Kak and Slaney) and accumulates the back projections by linear interpolation; phantom adds the ellipses on a grid.
dct2, idct2, dctmtx:
    Python: imgeom.py. scipy.fft.dctn and scipy.fft.idctn (type 2, orthonormal); dctmtx from the cosine formula.
# ---- optimprob.py: problem-based optimization ------------------------------------------------------------------------------------------
optimvar, optimexpr, optimconstr, optimineq, optimeq, optimproblem, eqnproblem, show, showbounds:
    Python: optimprob.py. An expression is a tree of array operations, each node knowing its size and degree (0 constant, 1 linear, 2 quadratic, otherwise nonlinear). Its coefficients are carried up the tree as sparse forms (scipy.sparse): A*v + b plus products of two linear forms summed by a sparse matrix; a node the forms do not follow is evaluated instead, at zero and at the unit vectors (and their pairwise sums for a quadratic). Values are computed with NumPy at many points at once (a last dimension for the points). The solver's vector holds the variables in alphabetical order of their names, each by columns. Constraints keep lhs - rhs and the relation, element by element.
solve, prob2struct, varindex:
    Python: optimprob.py. Linear constraints become the rows of A and Aeq from the forms, nonlinear ones a nonlcon function; then optim.py's linprog or intlinprog (scipy.optimize.linprog and milp, HiGHS), quadprog with H from the forms, fminunc or fmincon, or globalopt.py's ga, particleswarm, patternsearch or surrogateopt, each called as a function of the vector. Linear equations: numpy.linalg.lstsq (lsqlin with bounds); others fsolve or lsqnonlin.
evaluate, infeasibility:
    Python: optimprob.py. The expression's tree evaluated with NumPy at the point's values.
fcn2optimexpr:
    Python: optimprob.py. The function called with the expressions themselves first; when that fails or gives something else, a node that calls it (through the runtime, synchronously) at each point.
paretosearch:
    Python: optimprob.py. PyLAB's own scalarization: globalopt.py's patternsearch on each objective alone, then on a log-sum-exp smooth maximum of the weighted, scaled objectives for evenly spread weights (a simplex lattice for three or more objectives); nondominated points kept, thinned by globalopt.py's crowding distance.
"""


def _parse(text):
    """name -> [('p', paragraph) | ('pre', [formula lines])]; the names of
    a shared entry get the same list."""
    table = {}
    blocks = []         # (what comes before the first name goes nowhere)
    para = []

    def close():
        if para:
            blocks.append(('p', ' '.join(para)))
        para.clear()
    for line in text.split('\n'):
        if line.startswith('#'):
            continue
        if not line.strip():
            close()
            continue
        if not line.startswith(' '):
            close()
            blocks = []
            for name in line.rstrip().rstrip(':').split(','):
                table[name.strip()] = blocks
        elif line.startswith('        '):
            close()
            if blocks and blocks[-1][0] == 'pre':
                blocks[-1][1].append(line[8:])
            else:
                blocks.append(('pre', [line[8:]]))
        else:
            para.append(line.strip())
    close()
    return table


HOW = _parse(_TEXT)


# ---- the functions of each distribution family (normpdf, normcdf, ..., gamfit, gamlike) ------------

# each family's scipy.stats distribution, made from the language's parameters
_FAMILIES = (
    ('norm', 'norm(mu, sigma)', ''),
    ('logn', 'lognorm(sigma, scale=exp(mu))', ''),
    ('exp', 'expon(scale=mu)', ''),
    ('gam', 'gamma(a, scale=b)', ''),
    ('beta', 'beta(a, b)', ''),
    ('wbl', 'weibull_min(B, scale=A)', ''),
    ('unif', 'uniform(a, b - a)', ' (a location a and a scale b - a)'),
    ('unid', 'randint(1, N + 1)', ''),
    ('bino', 'binom(N, p)', ''),
    ('poiss', 'poisson(lambda)', ''),
    ('geo', 'geom(p, loc=-1)', ' (moved down by 1, so that x counts the failures)'),
    ('nbin', 'nbinom(R, p)', ''),
    ('hyge', 'hypergeom(M, K, N)', ''),
    ('chi2', 'chi2(nu)', ''),
    ('ncx2', 'ncx2(nu, delta)', ''),
    ('t', 't(nu)', ''),
    ('nct', 'nct(nu, delta)', ''),
    ('f', 'f(nu1, nu2)', ''),
    ('ncf', 'ncf(nu1, nu2, delta)', ''),
    ('ev', 'gumbel_l(mu, sigma)', ' (the extreme value distribution of minima)'),
    ('gev', 'genextreme(-k, mu, sigma)', " (SciPy's shape is -k)"),
    ('gp', 'genpareto(k, theta, sigma)', ''),
    ('rayl', 'rayleigh(scale=B)', ''),
)
_DISCRETE = {'unid', 'bino', 'poiss', 'geo', 'nbin', 'hyge'}
_LIKES = {'norm', 'logn', 'exp', 'gam', 'beta', 'wbl', 'ev', 'gev', 'gp', 'nbin'}

_WALD = ('The intervals are Wald intervals from the covariance, the inverse of the Hessian of the negative log-likelihood '
         'by central differences, taken on the log scale for positive parameters and on the logit scale for probabilities.')
_FITS = {
    'logn': 'mu and sigma are the mean and the std (n - 1) of log(x), with the intervals normfit gives for log(x).',
    'exp': ('mu = mean(x), the maximum likelihood estimate, with the exact interval 2*n*mu./chi2inv([1 - alpha/2, alpha/2], 2n) '
            'from scipy.stats.chi2.'),
    'poiss': ('lambda = mean(x), the maximum likelihood estimate, with the exact interval from scipy.stats.chi2: '
              'chi2inv(alpha/2, 2*sum(x))/(2n) to chi2inv(1 - alpha/2, 2*sum(x) + 2)/(2n).'),
    'rayl': ('B = sqrt(sum(x.^2)/(2n)), the maximum likelihood estimate, with the exact interval '
             'sqrt(sum(x.^2)./chi2inv([1 - alpha/2, alpha/2], 2n)) from scipy.stats.chi2.'),
    'nbin': ("R maximises the likelihood with p = R/(R + mean(x)): scipy.optimize.minimize_scalar (Brent's method) over "
             'log(R), started from the moment estimate mean^2/(var - mean). Data whose variance is not above their mean '
             'are refused. ' + _WALD),
    'gam': "SciPy's maximum likelihood fit, scipy.stats.gamma.fit, with the location held at 0. " + _WALD,
    'beta': "SciPy's maximum likelihood fit, scipy.stats.beta.fit, with the location held at 0 and the scale at 1. " + _WALD,
    'wbl': "SciPy's maximum likelihood fit, scipy.stats.weibull_min.fit, with the location held at 0. " + _WALD,
    'ev': "SciPy's maximum likelihood fit, scipy.stats.gumbel_l.fit. " + _WALD,
    'gev': "SciPy's maximum likelihood fit, scipy.stats.genextreme.fit (whose shape is -k). " + _WALD,
    'gp': "SciPy's maximum likelihood fit, scipy.stats.genpareto.fit, with the threshold held at 0. " + _WALD,
}


def _distribution_how():
    table = {}
    for code, call, note in _FAMILIES:
        dist = f"Python: distributions.py. SciPy's scipy.stats.{call}{note}"
        both = ' NumPy broadcasts x and the parameters together, and a place where a parameter is not valid gives NaN.'
        discrete = code in _DISCRETE
        table[code + 'pdf'] = f"{dist}: its {'pmf' if discrete else 'pdf'} at x.{both}"
        table[code + 'cdf'] = (f"{dist}: its cdf at x, or with 'upper' its sf, the survival function, which SciPy computes "
                               f'as such rather than as 1 - cdf.{both}')
        table[code + 'inv'] = (f"{dist}: its ppf, SciPy's inverse of the cdf, at p"
                               + (', the smallest whole x whose cdf reaches p' if discrete else '') + f'.{both}')
        table[code + 'rnd'] = (f"{dist}: its rvs, drawing from rand's generator (the numpy.random.RandomState that rng seeds), "
                               'with the parameters broadcast to the size asked for.')
        table[code + 'stat'] = f"{dist}: its stats with moments 'mv', SciPy's mean and variance."
        if code in _FITS:
            table[code + 'fit'] = 'Python: distributions.py. ' + _FITS[code]
        if code in _LIKES:
            table[code + 'like'] = (f"Python: distributions.py. -sum(log(f(x))), f being SciPy's scipy.stats.{call}"
                                    f" ({'logpmf' if discrete else 'logpdf'}); acov is the inverse of the Hessian of that "
                                    "sum by central differences, with steps of 1e-4 of each parameter's size.")
    return {name: [('p', text)] for name, text in table.items()}


HOW.update(_distribution_how())


def _qualification_how():
    from .helptext import _QUALS, _QUAL_KINDS
    table = {}
    for check, *_ in _QUALS:
        text = ('Python: unittests.py. ' + {
            'Equal': "PyLAB's own comparison: class_of and the sizes first, then NumPy's == with NaN equal to NaN (and |a - e| against the tolerances), cells and structs element by element, other values by isequaln.",
            'NotEqual': 'The comparison verifyEqual makes, the outcome turned round.',
            'Error': 'The function handle called, its error caught and its identifier compared.',
            'Warning': "The function handle called while the runtime keeps the warnings it issues (runtime.warn's WARN_CAPTURE), their identifiers compared.",
            'WarningFree': "The function handle called while the runtime keeps the warnings it issues (runtime.warn's WARN_CAPTURE).",
            'InstanceOf': 'isa of the value.',
            'Matches': "Python's re.search.",
        }.get(check, 'A check of the value in Python.') + ' The outcome is recorded with the running test (or shown, for interactive use); a failed assertion, fatal assertion or assumption raises an exception the runner catches.')
        shared = [('p', text)]
        for kind, *_ in _QUAL_KINDS:
            table[kind + check] = shared
    return table


HOW.update(_qualification_how())
