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
    Python: funfun.py. sol keeps the interpolant of each step (SciPy's OdeSolution over the solver's dense outputs, the same polynomials the solver's own help describes), and deval evaluates the one whose step holds each time. The interpolants were built during the solution, so deval evaluates odefun no more.
odextend:
    Python: funfun.py. The solver that made sol runs again from its last point (or the y0 given) to the new end, with sol's options unless others are given, and its steps and interpolants are joined to sol's.
# ---- elfun.py: element-wise mathematics -------------------------------------------------------
sqrt:
    Python: elfun.py. numpy.sqrt element by element, or math.sqrt for a scalar double. When a real argument has a negative element, the whole array is taken as complex and numpy.sqrt gives the complex roots, so sqrt(-4) is 0 + 2i. Char and logical count as double, single stays single, and integers are refused.
exp:
    Python: elfun.py. numpy.exp element by element, or math.exp for a scalar double (Inf above 709). Single stays single; integers are refused.
expm1:
    Python: elfun.py. numpy.expm1, which computes exp(x) - 1 without the cancellation near x = 0 (math.expm1 for a scalar double).
log, log10:
    Python: elfun.py. numpy.log and numpy.log10 element by element (math.log and math.log10 for a scalar double). When a real argument has a negative element the whole array is taken as complex, which gives log(-x) + pi*1i (pi/log(10) for log10); log(0) is -Inf.
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
    Python: elfun.py. 2.^x by NumPy's power. pow2(f, e) is f.*2.^e, by numpy.ldexp (an exact change of the exponent) when every e is a whole number.
nextpow2:
    Python: elfun.py. numpy.frexp of abs(x) gives x = f*2^e with f in [0.5, 1); the result is e, or e - 1 when f is exactly 0.5 (x is a power of two), 0 for 0 and Inf for Inf.
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
    Python: elfun.py. The argument is first reduced with mod(x, 360), then turned to radians (numpy.deg2rad) for numpy.sin, numpy.cos or numpy.tan. The values at whole multiples are set exactly: sind is 0 at multiples of 180, cosd at odd multiples of 90, and tand is 0, +-Inf and +-1 at multiples of 180, odd multiples of 90 and of 45. secd, cscd and cotd are the reciprocals.
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
    Python: elfun.py. a + b*1i as a complex double array (NumPy complex128). The result stays complex even where b is 0, unlike a + 0i.
isnan, isinf, isfinite:
    Python: elfun.py. numpy.isnan, numpy.isinf and numpy.isfinite for double and single values; integers, char and logical are never NaN or Inf. isnan of a string array is true for its missing strings; cells and structs are refused.
ismissing:
    Python: elfun.py. The standard missing value of each kind: NaN for numbers, a missing string in a string array, a space in char, and an empty char vector in a cell of text.
cplxpair:
    Python: elfun.py. Values whose imaginary part is below 100*eps*abs(z) count as real. The others with a negative imaginary part are sorted by real part (then imaginary part), each followed by its conjugate, and the real ones come last, sorted.
unwrap:
    Python: elfun.py. numpy.unwrap along the rows of a row vector and down the columns otherwise: a jump larger than the tolerance (pi unless given) is taken back by a multiple of 2*pi.
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
    Python: elfun.py. Trial division by 2 and the odd numbers up to sqrt(x), in Python's integers, for each element.
factor:
    Python: elfun.py. Trial division by 2 and then the odd numbers, in Python's integers; what is left above 1 is the last prime factor.
perms:
    Python: elfun.py. itertools.permutations of the vector taken from its end, so the rows come in reverse lexicographic order of positions.
rats:
    Python: elfun.py. Each value as text in the rational display format (the one format rat uses), padded to 13 characters.
rat:
    Python: elfun.py. A continued fraction: the whole part k is taken off and the rest inverted, the convergents n/d built up, until abs(x - n/d) is within the tolerance (1e-6*norm(x, 1) unless given), at most 64 terms. With one output, the text of the fractions.
gamma, gammaln, erf, erfc, erfinv, erfcinv, erfcx:
    Python: elfun.py. The SciPy function of the same name: scipy.special.gamma, scipy.special.gammaln, scipy.special.erf, scipy.special.erfc, scipy.special.erfinv, scipy.special.erfcinv, scipy.special.erfcx, element by element. Single stays single; integers are refused.
expint:
    Python: elfun.py. scipy.special.exp1, the exponential integral E1(x), element by element.
psi:
    Python: elfun.py. scipy.special.digamma; psi(k, x) is scipy.special.polygamma(k, x).
gammainc, gammaincinv:
    Python: elfun.py. scipy.special.gammainc and scipy.special.gammaincinv, or scipy.special.gammaincc and scipy.special.gammainccinv for 'upper'. SciPy takes the arguments the other way round: gammainc(x, a) here is gammainc(a, x) there.
beta, betaln:
    Python: elfun.py. scipy.special.beta and scipy.special.betaln (the logarithm, without overflow), with implicit expansion.
betainc, betaincinv:
    Python: elfun.py. scipy.special.betainc(z, w, x), or scipy.special.betaincc for 'upper', and scipy.special.betaincinv(z, w, y).
besselj, bessely, besseli, besselk:
    Python: elfun.py. scipy.special.jv, scipy.special.yv, scipy.special.iv and scipy.special.kv, or the scaled scipy.special.jve, scipy.special.yve, scipy.special.ive and scipy.special.kve when the third input is 1. Complex arithmetic is used where the real function is undefined: a negative argument with an order that is not whole, and any negative argument for bessely.
besselh:
    Python: elfun.py. scipy.special.hankel1, or scipy.special.hankel2 for k = 2.
airy:
    Python: elfun.py. scipy.special.airy gives Ai, Ai', Bi and Bi' together; k (0 to 3) picks one.
ellipke:
    Python: elfun.py. scipy.special.ellipk and scipy.special.ellipe of the parameter m.
ellipj:
    Python: elfun.py. scipy.special.ellipj(u, m), whose sn, cn and dn are returned.
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
    Python: elmat.py. numpy.finfo(float).eps (2^-52), or that of single; eps(x) is numpy.spacing(abs(x)), the distance from abs(x) to the next larger number of its class, and NaN for Inf and NaN.
realmax, realmin, flintmax:
    Python: elmat.py. numpy.finfo's max and tiny (the largest and the smallest normalised double or single), and 2^53 or 2^24, the largest whole numbers that every smaller whole number is exact below.
intmax, intmin:
    Python: elmat.py. The largest and smallest value of the integer class (int32 unless named), in that class.
eye:
    Python: elmat.py. numpy.eye with the rows and columns asked for, in the class asked for.
rand:
    Python: elmat.py. One generator for the session: NumPy's Mersenne Twister, numpy.random.RandomState, seeded with 5489 by default and by rng. rand draws its random_sample (uniform on [0, 1)) and fills the array down the columns. rand('seed', s) and the other old forms reseed it.
randn:
    Python: elmat.py. The standard_normal values of the same Mersenne Twister generator as rand, filling the array down the columns; 'complex' adds an imaginary part drawn the same way.
randi:
    Python: elmat.py. floor(u*(imax - imin + 1)) + imin from the uniform values u of rand's generator, in the class asked for.
randperm:
    Python: elmat.py. n uniform values from rand's generator, and the order that sorts them (numpy.argsort, stable): the first k positions of that order.
rng:
    Python: elmat.py. Seeds the generator of rand, randn and randi: a whole number from 0 to 2^32 - 1 (0 is the default seed, 5489), 'default', or 'shuffle' (the clock in milliseconds). It returns the previous settings as a struct.
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
    Python: elmat.py. numpy.flatnonzero of the array taken down its columns; rows and columns from the remainder and quotient by the number of rows; find(x, k, 'last') keeps the last k.
nnz:
    Python: elmat.py. numpy.count_nonzero.
nonzeros:
    Python: elmat.py. The nonzero elements in column order, as a column.
fliplr, flipud, flip:
    Python: elmat.py. NumPy's reversed slicing a[:, ::-1] and a[::-1], or numpy.flip along a dimension (the first one whose size is not 1 unless given).
rot90:
    Python: elmat.py. numpy.rot90, k quarter turns counterclockwise.
circshift:
    Python: elmat.py. numpy.roll by the shifts given, along the first dimension whose size is not 1 (or the dimension given, or dimension by dimension for a vector of shifts).
tril, triu:
    Python: elmat.py. numpy.tril and numpy.triu with the diagonal offset k.
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
    Python: elmat.py. The subscripts are turned into linear indices (numpy.ravel_multi_index in column order) and the values summed into them with numpy.add.at, which adds repeated indices once each; places nothing went to get the fill value. With a function, the values of each place are gathered in a Python list in the order they come and the function called once for each place.
double, single, logical, int8, uint8, int16, uint16, int32, uint32, int64, uint64:
    Python: elmat.py. NumPy's astype to the class's type. To an integer class, a value is rounded to the nearest whole number with halves away from zero, NaN becomes 0, and values beyond the class's range saturate at its ends; an integer value converts exactly, without a round trip through doubles (int64 and uint64 hold more than a double can). logical refuses NaN and complex values. double of a string array reads each string as a number (NaN where it is not one).
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
    Python: datafun.py. numpy.mean, or numpy.nanmean with 'omitnan', along the first dimension whose size is not 1 or the one given; an empty dimension gives NaN. Integers, logical and char are averaged in doubles and give double ('native' returns an integer class); single stays single. A probability distribution object gives its own mean.
median:
    Python: datafun.py. numpy.median, or numpy.nanmedian with 'omitnan' (an empty dimension gives NaN); single stays single. A probability distribution object gives its own median.
mode:
    Python: datafun.py. numpy.unique with counts for each vector along the dimension, NaN left out: the most frequent value, the smallest of those tied. The second output is the frequency and the third a cell with all the tied values.
var, std:
    Python: datafun.py. numpy.var (numpy.nanvar with 'omitnan') with ddof 1, dividing by n - 1, or ddof 0 (by n) when w is 1; a vector of weights w gives the weighted variance about the weighted mean. A single element gives 0; std is the square root. A probability distribution object gives its own.
range:
    Python: datafun.py. numpy.nanmax minus numpy.nanmin along the dimension.
max, min:
    Python: datafun.py. Along a dimension, numpy.argmax or numpy.argmin pick the position: NaN is left out (taken as -Inf or Inf) unless 'includenan', and a column of NaN gives NaN; complex values compare by magnitude; the second output is the position from 1 (or the linear index with 'linear'). With two arrays, numpy.fmax and numpy.fmin element by element (numpy.maximum and numpy.minimum with 'includenan'), and for complex values by magnitude and then angle. Two scalars compare directly.
bounds:
    Python: datafun.py. min and max of the data, by the code of min and max.
any, all:
    Python: datafun.py. numpy.any and numpy.all of x ~= 0 along the first dimension whose size is not 1 or the one given; NaN does not count as true for any. A vector gives one logical.
xor, not, and, or:
    Python: datafun.py and ops.py. The language's logical operators: the code that runs xor, ~a, a & b and a | b in expressions, with implicit expansion; and(a, b, ...) and or(a, b, ...) take any number of arguments, left to right.
sort:
    Python: datafun.py. A stable sort of each vector along the dimension (numpy.argsort with kind 'stable', so equal values keep their order): NaN goes last ascending and first descending, complex values sort by magnitude and then angle (numpy.lexsort), and the second output is the order from 1. Cells of text and string arrays sort in Python by the characters' codes.
sortrows:
    Python: datafun.py. One stable sort per column, from the last column named to the first, so the first column given decides first; a negative column number sorts that column descending. Cells are sorted in Python, text against text and numbers against numbers.
issorted:
    Python: datafun.py. True when each element is no larger than the next (complex values by magnitude).
unique:
    Python: datafun.py. numpy.unique with its first indices and the inverse map, giving C, ia and ic; every NaN counts as a distinct value and they come last; complex values are ordered by magnitude, then angle. 'stable' reorders C by first appearance; 'last' takes the last index; 'rows' compares rows as tuples in Python. Text in cells and string arrays is handled in Python, sorted by the characters' codes, and graphics objects by their handle numbers, coming back as objects.
ismember:
    Python: datafun.py. numpy.isin for the logical result; the locations come from a Python dictionary of each value's first position in s. Text and 'rows' compare in Python as strings and tuples, graphics objects by their handle numbers.
union, intersect, setdiff, setxor:
    Python: datafun.py. The elements become Python lists and their first positions a dictionary; the result is the union, intersection, difference or symmetric difference of their sets, sorted (complex values by magnitude and angle) or, with 'stable', in the order the values first appear. ia and ib point to the first occurrences. Text and 'rows' work the same way on strings and row tuples, and graphics objects by their handle numbers, coming back as objects.
histcounts:
    Python: datafun.py. With no edges given, a bin width is chosen by Scott's rule, 3.5*std(x)/n^(1/3), and rounded to 1, 2 or 5 times a power of ten (at most 1000 bins), with the edges on its multiples; a number of bins gets a round width too, or exact limits when a round one cannot cover the data. Each value goes to the bin [e(k), e(k+1)) found by numpy.searchsorted, the last bin closed on the right, and numpy.bincount counts them. The normalisations divide by the number of values or the bin widths, or add up with numpy.cumsum.
histc:
    Python: datafun.py. numpy.searchsorted of each value into the edges: bin k holds edges(k) <= x < edges(k+1), and the last bin the values equal to edges(end); numpy.bincount counts them.
discretize:
    Python: datafun.py. numpy.searchsorted into the edges, the last bin closed on the right; values outside the edges and NaN give NaN.
cov:
    Python: datafun.py. numpy.cov with the observations in rows and the variables in columns, normalised by n - 1 (by n when w is 1); cov(x, y) puts x and y in two columns.
corrcoef:
    Python: datafun.py. numpy.corrcoef with the variables in columns. The p-values test each correlation with the t statistic r*sqrt((n - 2)/(1 - r^2)) and two tails of scipy.stats.t.
trapz:
    Python: datafun.py. numpy.trapezoid (trapz on a NumPy older than 2.0) along the first dimension whose size is not 1 or the one given, with unit spacing, a scalar spacing, or the points x.
cumtrapz:
    Python: datafun.py. scipy.integrate.cumulative_trapezoid with initial 0, along the first dimension whose size is not 1, with unit spacing, a scalar spacing or the points x.
quantile, prctile:
    Python: datafun.py. For each vector the values are sorted (NaN left out) and placed at the probabilities (i - 0.5)/n; numpy.interp interpolates linearly between them, and p below the first or above the last gives the smallest or largest value. quantile(x, n) asks for the probabilities (1:n)/(n + 1); prctile divides p by 100.
iqr:
    Python: datafun.py. The difference of the 0.75 and 0.25 quantiles, computed as quantile computes them. A probability distribution object gives its own.
skewness, kurtosis:
    Python: datafun.py. scipy.stats.skew and scipy.stats.kurtosis (with fisher False, so a normal sample gives about 3) along the first dimension whose size is not 1; flag 0 corrects the bias.
rescale:
    Python: datafun.py. lo + (x - min(x))/(max(x) - min(x))*(hi - lo), the minimum and maximum by numpy.nanmin and numpy.nanmax; a constant x gives lo.
normalize:
    Python: datafun.py. The z-score (x - mean(x))./std(x) along the first dimension whose size is not 1, std with n - 1.
movmean, movsum, movmax, movmin, movmedian, movstd:
    Python: datafun.py. For each position, NumPy's mean, sum, max, min, median or std (n - 1) of the window around it, shortened at the ends of the vector: k elements centred (for an even k, one more before than after), or [kb kf] before and after.
# ---- matfun.py: linear algebra -----------------------------------------------------------------
inv:
    Python: matfun.py. numpy.linalg.inv, after an LU factorisation (scipy.linalg.lu_factor) gives LAPACK's estimate of the reciprocal condition number (its gecon routine, in the 1-norm): a zero pivot gives Inf and the singular-matrix warning, an estimate below eps the close-to-singular warning, and NaN or Inf in the matrix a matrix of NaN.
det:
    Python: matfun.py. numpy.linalg.det: the product of the pivots of an LU factorisation with partial pivoting; det([]) is 1.
trace:
    Python: matfun.py. numpy.trace, the sum of the diagonal of a square matrix.
rank:
    Python: matfun.py. The number of singular values (numpy.linalg.svd, values only) above the tolerance max(size(A))*eps(max(s)), or the one given.
norm:
    Python: matfun.py. For a vector, numpy.linalg.norm with p (max(abs(v)) for Inf, the smallest for -Inf, the count of nonzeros for 0). For a matrix: the 2-norm is the largest singular value (numpy.linalg.svd), the 1-norm the largest column sum of abs(A), Inf the largest row sum, and 'fro' the 2-norm of all the elements.
vecnorm:
    Python: matfun.py. sum(abs(A).^p).^(1/p) along the first dimension whose size is not 1 or the one given, or max(abs(A)) for p = Inf.
cond:
    Python: matfun.py. The ratio of the largest to the smallest singular value (numpy.linalg.svd) for the 2-norm, Inf when the smallest is 0; numpy.linalg.cond for the 1, Inf and 'fro' norms.
rcond:
    Python: matfun.py. LAPACK's estimate of the reciprocal condition number in the 1-norm (its gecon routine, by scipy.linalg.lapack.get_lapack_funcs) from an LU factorisation by scipy.linalg.lu_factor; 0 when the factorisation fails.
condest:
    Python: matfun.py. numpy.linalg.cond in the 1-norm, computed exactly rather than estimated.
eig:
    Python: matfun.py. A matrix equal to its conjugate transpose goes to numpy.linalg.eigh (numpy.linalg.eigvalsh for the values alone), which gives real values in increasing order and orthonormal vectors; any other to numpy.linalg.eig, and eig(A, B) to scipy.linalg.eig. The third output, the left vectors, comes from scipy.linalg.eig with left=True. 'vector' returns the values as a column. NaN or Inf in A is refused.
eigs:
    Python: matfun.py. All eigenvalues by numpy.linalg.eig, of which the k (6 unless given) of largest magnitude are kept; a dense method, not an iterative one.
svd:
    Python: matfun.py. numpy.linalg.svd: the singular values alone as a column, or U, S and V with S placed in a matrix of A's size; 'econ' (and svd(A, 0) for a tall A) keeps only min(m, n) of them. NaN or Inf is refused.
svds:
    Python: matfun.py. The full numpy.linalg.svd, of which the k (6 unless given) largest are kept.
qr:
    Python: matfun.py. scipy.linalg.qr: R alone, Q and R, or with three outputs the factorisation with column pivoting (A(:, p) = Q*R) and its permutation as a matrix, or as a vector with 'vector'; 'econ' (or 0) gives the economy size.
lu:
    Python: matfun.py. scipy.linalg.lu (partial pivoting): with two outputs the permuted L and U, with three L, U and the permutation matrix P (or a vector with 'vector'); with one output the two factors in one matrix.
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
    Python: matfun.py. scipy.linalg.expm (scaling and squaring with a Pade approximant), scipy.linalg.logm and scipy.linalg.sqrtm (both by the Schur form).
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
    Python: matfun.py and ops.py. The element-wise operator (+, -, .*, ./, .\, .^, ==, ~=, <, <=, >, >=) as the expressions run it: NumPy's add, subtract, multiply, true_divide, power and comparisons with implicit expansion, the class of the result by the language's rules (integers saturate, single wins over double), and .^ going to complex arithmetic where a negative number has a fractional power. plus and times take more than two arguments, left to right.
mtimes:
    Python: matfun.py and ops.py. The operator *: a scalar times an array element by element, two matrices by NumPy's matrix product (@), in single when either is single; integer matrices are refused.
mldivide, mrdivide:
    Python: matfun.py and ops.py. The operators \ and /, with A/B solved as (B'\A')'. A square triangular A is solved by back or forward substitution (scipy.linalg.solve_triangular); any other square A by an LU factorisation with partial pivoting (scipy.linalg.lu_factor and scipy.linalg.lu_solve), with LAPACK's condition estimate behind the singular and close-to-singular warnings. A rectangular A gets a least-squares solution from a QR factorisation with column pivoting (scipy.linalg.qr): the basic solution with as many nonzeros as the numerical rank, with a warning when that is below full rank. NaN or Inf in A gives NaN.
mpower:
    Python: matfun.py and ops.py. The operator ^: a whole power by numpy.linalg.matrix_power (repeated squaring), a negative one of the inverse (A\eye); another power by scipy.linalg.fractional_matrix_power; a scalar to a matrix power by scipy.linalg.expm(log(s)*B).
uminus, uplus, transpose, ctranspose:
    Python: matfun.py and ops.py. The operators -a, +a, a.' and a': negation (integers through doubles and back, so -int8(-128) saturates), and NumPy's transpose, with the complex conjugate for '.
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
    Python: symmath.py. sympy.series about the point to the order given (6 unless given), without its O(...) term.
symsum, symprod:
    Python: symmath.py. sympy.summation and sympy.product over k from a to b (from 0 to k-1 for the indefinite sum).
jacobian, hessian, divergence, curl, laplacian:
    Python: symmath.py. sympy.Matrix's jacobian and sympy.hessian; the others from sympy.diff of each component.
simplify, simplifyFraction:
    Python: symmath.py. sympy.simplify, after expand_log, powdenest and logcombine with force=True for 'IgnoreAnalyticConstraints'; simplifyFraction is sympy.cancel of sympy.together.
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
    Python: symmath.py. sympy.solve with dict=True on the equations as expression == 0 (cubics solved by radicals, quartics only with 'MaxDegree' 4), solutions kept when they agree with the variables' assumptions and the inequalities assumed; 'Real' solves for real symbols. 'ReturnConditions' uses sympy.solveset: a family k*pi + c (an ImageSet) becomes a solution in k with the condition in(k, 'integer'). Inequalities go to sympy.solve as they are.
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
    Python: funfun.py. scipy.integrate.quad, QUADPACK's adaptive Gauss-Kronrod quadrature (21 points on a finite interval; an infinite one is mapped onto a finite one), with RelTol 1e-6 and AbsTol 1e-10 unless given, at most 650 subintervals, and the Waypoints as break points. The function is called one point at a time. For complex values the real and imaginary parts are integrated separately; 'ArrayValued' uses scipy.integrate.quad_vec.
quad, quadl, quadgk:
    Python: funfun.py. scipy.integrate.quad (QUADPACK's adaptive Gauss-Kronrod rule) with the tolerance given (1e-6 unless given); the second output is its error estimate.
integral2, quad2d, dblquad:
    Python: funfun.py. scipy.integrate.dblquad, QUADPACK's quadrature in y inside quadrature in x, with the y limits numbers or functions of x; AbsTol 1e-10 and RelTol 1e-6.
integral3, triplequad:
    Python: funfun.py. scipy.integrate.tplquad: three nested QUADPACK quadratures over the limits given, with SciPy's default tolerances.
interp1:
    Python: funfun.py. The points x are sorted first (repeated x is refused) and each column of V interpolated. 'linear' (the default) is numpy.interp, NaN outside x unless 'extrap' (scipy.interpolate.interp1d then extends the end pieces) or an extrapolation value. 'nearest', 'next' and 'previous' are scipy.interpolate.interp1d of that kind; 'pchip' and 'cubic' are scipy.interpolate.PchipInterpolator; 'makima' is scipy.interpolate.Akima1DInterpolator with method 'makima'; 'spline' is scipy.interpolate.CubicSpline with not-a-knot ends (natural ends for three points). These last four extrapolate unless a value is given.
interp2, interpn:
    Python: funfun.py. scipy.interpolate.RegularGridInterpolator on the grid's axes, with method 'linear', 'nearest' or 'cubic' ('spline' and 'makima' are taken as 'cubic'); points outside the grid get NaN or the extrapolation value given.
griddata:
    Python: funfun.py. scipy.interpolate.griddata on scattered points, by a Delaunay triangulation: linear in each triangle, nearest, or cubic (Clough-Tocher); 'natural' is taken as linear and 'v4' as cubic.
spline:
    Python: funfun.py. scipy.interpolate.CubicSpline with not-a-knot ends (natural ends for three points); with two more values than points, the first and last are the end slopes (clamped ends). With two inputs it returns the piecewise polynomial, its coefficients taken from SciPy's.
pchip:
    Python: funfun.py. scipy.interpolate.PchipInterpolator: piecewise cubic Hermite interpolation with slopes chosen to keep the data's monotonicity (Fritsch and Carlson); with two inputs, the piecewise polynomial.
makima:
    Python: funfun.py. scipy.interpolate.Akima1DInterpolator with method 'makima', extrapolating at the ends.
ppval:
    Python: funfun.py. Each point's piece is found by numpy.searchsorted on the breaks (the end pieces extend outside them), and its polynomial evaluated by Horner's rule in x - breaks(k).
mkpp, unmkpp:
    Python: funfun.py. A piecewise polynomial object holding the breaks and the coefficients (one row per piece, highest power first), and back.
polyfit:
    Python: funfun.py. The Vandermonde matrix of x (numpy.vander) and the least-squares coefficients by numpy.linalg.lstsq, with a warning when the matrix's rank is below the degree plus one. S holds R from numpy.linalg.qr of that matrix, the degrees of freedom, the norm of the residuals and R^2. With three outputs x is first centred and scaled, by mu = [mean(x); std(x)].
polyval:
    Python: funfun.py. Horner's rule, element by element by NumPy (y = y.*x + c for each coefficient); with mu, x is first centred and scaled.
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
    Python: funfun.py. scipy.signal.residue: the partial fraction expansion of b/a, residues, poles and the direct term.
filter:
    Python: funfun.py. scipy.signal.lfilter, the direct form II transposed structure, along the first dimension whose size is not 1 or the one given, with the initial conditions zi and the final ones returned.
filter2:
    Python: funfun.py. scipy.signal.correlate2d, the kernel slid over the data without being rotated, 'same' size unless asked otherwise.
conv2:
    Python: funfun.py. scipy.signal.convolve2d with 'full', 'same' or 'valid'; conv2(u, v, A) convolves A with the column u and the row v.
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
    Python: funfun.py. numpy.gradient: central differences inside, one-sided ones at the ends, with the spacing given; for a matrix the derivative along the rows (x) comes first and along the columns (y) second.
del2:
    Python: funfun.py. numpy.gradient applied twice along each dimension, the results added and divided by 4.
# ---- sparse.py: sparse matrices, held dense ------------------------------------------------------
sparse:
    Python: sparse.py. Sparse matrices are held as ordinary dense NumPy arrays: the functions take the same arguments and give the same numbers, without the saving of memory. sparse(i, j, v, m, n) adds each value into its place with numpy.add.at, so repeated subscripts are summed; sparse(m, n) is a matrix of zeros and sparse(A) is A.
full:
    Python: sparse.py. The value as it is: sparse matrices are already full here.
speye, spzeros, spalloc:
    Python: sparse.py. numpy.eye and numpy.zeros of the size asked for (dense).
spones:
    Python: sparse.py. 1 where A is nonzero, 0 elsewhere, in doubles.
sprand, sprandn:
    Python: sparse.py. Uniform values from rand's generator, kept where a second set of uniform values is below the density d and zero elsewhere (sprandn draws the same uniform values).
spdiags:
    Python: sparse.py. In Python loops: the diagonals of A as the columns of B, or B's columns put on the diagonals d of an m-by-n matrix, each diagonal aligned by the column of A when m >= n and by the row otherwise.
nzmax:
    Python: sparse.py. The number of nonzero elements (numpy.count_nonzero), as nothing is allocated beyond them.

# ---- timefun.py: dates and times as numbers -----------------------------------------------------
clock, now, date:
    Python: timefun.py. Python's datetime.now (the browser's local time): as [year month day hour minute seconds], as a date number, or as 'dd-mmm-yyyy'.
datenum:
    Python: timefun.py. Days from year 0: Python's date ordinal (days from 1 January of year 1) plus 366, and the time of day as a fraction; months past 12 roll into the years. Text is read with Python's datetime.strptime, trying the formats yyyy-mm-dd HH:MM:SS, yyyy-mm-dd, dd-mmm-yyyy (with or without the time), mm/dd/yyyy, mm/dd/yy, yyyy/mm/dd, HH:MM:SS and dd.mm.yyyy in turn.
datevec:
    Python: timefun.py. The date number taken apart with Python's datetime (whole days through the date ordinal, the fraction as seconds rounded to microseconds) into year, month, day, hour, minute and seconds; text goes through datenum first.
datestr:
    Python: timefun.py. Python's strftime: the numbered formats 0, 1, 2, 13, 23, 29, 30 and 31, or a pattern of yyyy, mmm, dd, HH, MM, SS, FFF and the like translated to strftime's codes; a whole date number is shown without its time.
weekday:
    Python: timefun.py. mod(floor(d) - 2, 7) + 1, so 1 is Sunday, and the day's short name.
eomday, leapyear:
    Python: timefun.py. Python's calendar.monthrange and calendar.isleap.
etime:
    Python: timefun.py. Both date vectors as Python datetimes; the seconds from the second to the first.
addtodate:
    Python: timefun.py. Days, weeks, hours, minutes, seconds and milliseconds are added to the date number as fractions of a day; months and years are added to the date vector and turned back into a number.

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
issparse:
    Python: core.py. Always false: sparse matrices are held dense (see sparse).
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
    Python: core.py. Each character that is not a letter, digit or underscore becomes an underscore, and 'x' is put in front when the name does not start with a letter.
exist:
    Python: core.py. 1 for a variable of the calling workspace, 2 for a file found on the path or by name, 5 for a builtin, 7 for a folder, else 0; the second argument limits which kinds are looked for.
clear, clearvars:
    Python: core.py. Deletes names from the workspace's dictionary, with Python's fnmatch for the wildcards * and ? and re.match for -regexp; -except keeps the names given. clear all also empties the globals and the persistent variables, and clear functions the persistent variables, and both make files compile again on their next call.
who, whos:
    Python: core.py. The workspace's names, sorted without regard to case and filtered by the wildcards given. whos adds size, class and bytes: 8 a double, 1 a logical, 2 a character, the NumPy array's own byte count, and for cells and structs their elements' bytes plus a fixed 104 for each.
assignin:
    Python: core.py. Stores the value under the name in the base workspace, or in the calling function's, found by walking up Python's call stack to the compiled function that called this one.
evalin:
    Python: core.py. The text compiled and run as eval does, in the base workspace or in the calling function's (found as for assignin).
eval:
    Python: core.py and compiler.py. The text is compiled to Python as a line typed at the prompt would be and run in the calling workspace; when outputs are wanted it is compiled as an assignment to temporary names. When it fails and a second text is given, that one runs instead.
evalc:
    Python: core.py. eval with the Command Window's output kept aside: what the text prints is returned as text instead of shown.
feval:
    Python: core.py and runtime.py. Calls the function handle, or looks the name up as a call does (a local function, a file on the path, then a builtin) and calls it with the arguments.
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
more, echo, diary, profile:
    Python: core.py. Accepted and ignored.
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
    Python: core.py. Fixed text naming PyLAB, with Python's, NumPy's and SciPy's version numbers read from the running engine; computer is 'PYODIDE'.
ispc, isunix, ismac, isdeployed, usejava:
    Python: core.py. Fixed answers for the engine in the page: isunix is true (Pyodide's file system is Unix-like), the others false.
getenv, setenv:
    Python: core.py. Python's os.environ in the engine.
inputname:
    Python: core.py. Always '' (the names of the arguments are not kept).
mfilename:
    Python: core.py. Walks up Python's call stack to the first frame of compiled code and gives the name of the file it was compiled from (with 'fullpath', its path without .m); '' for a line typed at the prompt.
validateattributes:
    Python: core.py. The class against the list of classes ('numeric' and 'float' name groups), then each attribute tested in turn by NumPy: positive, nonnegative, scalar, vector, integer, finite, nonempty and the comparisons >, >=, < and <=; others are accepted without a test.
onCleanup:
    Python: core.py and runtime.py. An object that calls the function when Python deletes it: when the variable holding it is cleared or the function's workspace goes at its return.
# ---- strfun.py: text ----------------------------------------------------------------------
char:
    Python: strfun.py and values.py. Character arrays hold the characters' codes in a NumPy array of uint16. Numbers become codes: rounded down, negative ones and NaN to 0, and kept within 0 to 65535. Several arguments, a cell or a string array become the rows of a character matrix, the shorter rows padded with blanks.
string:
    Python: strfun.py and strings.py. String arrays are NumPy arrays of Python str objects (None for a missing string). Text converts as it is, each row of a character matrix to one string; a whole number is written in full, any other with 5 significant digits (Python's %.5g), a logical as true or false, and NaN becomes a missing string.
strings:
    Python: strfun.py. A string array of the size given, every element ''.
cellstr:
    Python: strfun.py. Each row of a character matrix, its trailing blanks removed, in a cell of one column; each string of a string array as a character vector in a cell of the same size.
blanks:
    Python: strfun.py. A row of n characters of code 32.
convertStringsToChars, convertCharsToStrings:
    Python: strfun.py. Each argument converted on its own: a string to a character vector (a string array to a cell of them), or a character vector or cell of them to a string array; the other arguments pass unchanged.
num2str:
    Python: strfun.py. A whole number is written in full. Any other number is written by Python's %g with max(floor(log10(abs(x))), 0) + 5 significant digits (so 4 decimals between 1 and 10), the exponent with a sign and at least two digits; a matrix gets the digits of its largest element, each column right-aligned and the columns two spaces apart. num2str(x, n) uses %.ng, and num2str(x, format) applies sprintf's code to each row.
int2str:
    Python: strfun.py. The values rounded to whole numbers, halves away from zero (as round does), then written as num2str writes them.
mat2str:
    Python: strfun.py. Each element by Python's %.15g (or the precision given): elements separated by spaces, rows by semicolons, in brackets unless there is one element; logical values as true and false, text in quotes, and with 'class' the class name around it.
str2num:
    Python: strfun.py. The text is compiled and run, as a line at the prompt would be, as the assignment of [text] in a workspace of its own, so any expression or function call in it is evaluated; when it fails the result is [] and the second output false.
str2double:
    Python: strfun.py. Regular expressions read each text as a whole: an optional sign, digits (commas between them are ignored), a decimal point, an exponent with e or d, Inf or NaN; or a complex number a+bi or bi. Python's float converts the matched digits. Anything else, and any element of a cell that is not text, gives NaN.
dec2bin, dec2hex, dec2base:
    Python: strfun.py. Python's format(n, 'b') and format(n, 'X'), or repeated division by the base with the digits 0-9 and A-Z; the texts padded on the left with zeros to n characters or to the longest of them.
bin2dec, hex2dec, base2dec:
    Python: strfun.py. Python's int(s, base) of each text with its blanks taken out, as a double.
num2hex, hex2num:
    Python: strfun.py. Python's struct.pack('>d') and struct.unpack: the eight bytes of the IEEE double, most significant first, as 16 hexadecimal digits; hex2num pads shorter texts with zeros on the right.
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
    Python: strfun.py. Python's str.find, started again one character after each hit so that overlapping occurrences are found; the positions from 1, a cell of them for a cell of texts.
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
    Python: strfun.py. Python's str.join with the delimiter (a space unless given; escapes such as \n become characters in strjoin); a cell of delimiters puts each one in its place. join joins along the rows of a string matrix.
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
    Python: iofun.py. Changes to the script's folder, compiles and runs the file (a script in the calling workspace, a function with no arguments), and changes back even when it fails.
web:
    Python: iofun.py. Tells the page to open the address in a new browser tab (window.open).
fopen, fclose:
    Python: iofun.py. Python's open in binary mode ('r', 'w', 'a' and their + forms; a t is ignored). The file objects are kept in a dictionary under identifiers from 3 up, with the encoding given (UTF-8 unless given) that the text functions use; fclose closes one or all of them.
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
    Python: iofun.py. The text (or the rest of the file) split into lines after the header lines, each line split by the delimiters (white space unless given), and the fields given to the format's conversions in turn: numbers by Python's float (NaN where a field is not a number), text as character vectors. The result is a cell with one column for each conversion.
readmatrix, csvread, dlmread:
    Python: iofun.py. Each line split by the delimiter given, or else by the first of comma, tab and semicolon it holds (white space when none), and each field read by Python's float, NaN when it is empty or text. Leading lines that are all text are dropped, and short rows padded with NaN.
writematrix, csvwrite, dlmwrite, writecell:
    Python: iofun.py. One line for each row, the elements joined by the delimiter (a comma unless given): whole numbers in full, others by %.15g, text as it is.
readcell:
    Python: iofun.py. Each line that is not blank split at the commas; a field that Python's float reads becomes a number, any other a character vector.
save:
    Python: iofun.py. SciPy's scipy.io.savemat writes a Level 5 MAT-file, compressed for -v7 (the default, and for -v7.3, as SciPy does not write HDF5), uncompressed for -v6, or a Level 4 file for -v4; text, cells and structs go to it as NumPy arrays of strings and objects and as dictionaries. -append reads the file first and writes all of it again, refusing when a variable it holds could not be read back. -ascii writes the numbers as text by %.7e (%.16e with -double). Function handles and objects are not saved.
load:
    Python: iofun.py and matfile.py. MAT-files are read by PyLAB's own reader: Level 4 and Level 5 files, compressed or not, in either byte order, with string arrays from the file's object data; -v7.3 files are HDF5 and are read through h5py, which Pyodide loads the first time. Nothing in a file is trusted: sizes are checked against the data, inflated data is capped and nesting is limited, and a variable that cannot be read is reported while the others are read. Any other file is read as readmatrix reads it, into a variable named after the file. coastlines, when no such file is found, is Natural Earth's coastline GeoJSON (geodata.py, fetched by pyfetch once a session), its lines joined into coastlat and coastlon with NaN between them.
matfile:
    Python: iofun.py. All the variables of the MAT-file read at once, as load reads them, into a struct.
importdata:
    Python: iofun.py. A MAT-file read as load reads it (one variable alone, several in a struct); any other file read as readmatrix reads it.
textread:
    Python: iofun.py. The whole file, after the header lines and comments are taken out, read with the format again and again: %d, %f, %n and %u numbers (an empty field gets the empty value), %s words, %q quoted text, %c characters and %[...] sets, with the literal text matched. One output for each conversion that is not skipped with *.
# ---- cellfun.py: cells, structs and maps ---------------------------------------------------------
cell:
    Python: cellfun.py and values.py. A cell array is a NumPy array of Python objects, each element any value; cell(n) fills one of the size given with [].
num2cell:
    Python: cellfun.py. Each element in a cell of its own, keeping its class (a struct's elements, a string's strings, a character's characters); with dims, the slices along those dimensions instead.
cell2mat:
    Python: cellfun.py and ops.py. Each row of the cell concatenated as [a, b, ...] would be, then the rows stacked as [r1; r2; ...]; cells that hold cells or function handles are refused.
cell2struct:
    Python: cellfun.py. The cell's elements along the dimension given (the first unless given) become the named fields, and the other dimensions the struct array's size.
struct2cell:
    Python: cellfun.py. The fields' values as a cell with one row for each field (and the struct array's dimensions after it).
struct:
    Python: cellfun.py and values.py. A struct array is a Python dictionary from field names, in their order, to NumPy object arrays of the struct's size. A cell value spreads over a struct array of the cell's size, a 1-by-1 cell gives its content to every element, and any other value goes to every element.
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
    Python: statdesc.py. The mean of abs(x - mean(x)), or with flag 1 the median of abs(x - median(x)), with NaN left out.
moment:
    Python: statdesc.py. mean((x - mean(x)).^k): the central moment, divided by n.
zscore:
    Python: statdesc.py. (x - mean(x))./std(x) by NumPy, std with n - 1 (n with flag 1); a vector with no spread gives zeros. The mean and std are the second and third outputs.
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
    Python: statdesc.py. Pearson's r by numpy.corrcoef for each pair of columns, the p-value from t = r*sqrt((n - 2)/(1 - r^2)) and the survival function of scipy.stats.t. Spearman's is Pearson's on the ranks (scipy.stats.rankdata, ties averaged); Kendall's is scipy.stats.kendalltau (tau-b) with its own p-value. 'Rows', 'complete' drops the rows with any NaN and 'pairwise' those of each pair; a one-sided 'Tail' halves the two-sided p-value on the side of r.
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
    Python: distributions.py. With a name, the distribution is looked up by its whole name, its prefix (norm) or its makedist name, in any case, and the value is the one normpdf, normcdf and norminv and the others give. With a distribution object, its own SciPy distribution's pdf (pmf when discrete), cdf (sf with 'upper') or ppf. A truncated object's values are taken between its limits: pdf/(F(hi) - F(lo)), (F(x) - F(lo))/(F(hi) - F(lo)), and the ppf of F(lo) + p*(F(hi) - F(lo)).
random:
    Python: distributions.py. With a name, as normrnd and the others draw; with an object, its SciPy distribution's rvs from rand's generator, or for a truncated object the ppf of uniform numbers between F(lo) and F(hi).
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
    Python: graphics.py. Runs the figure's CloseRequestFcn, whose default, closereq, deletes the figure; 'force' deletes it without asking. 'all' closes each figure whose handle is visible ('all hidden' the others too), and a name closes the figures with that Name.
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
    Python: graphics.py. The arguments are split into groups of x, y (and z) and a line specification; each column of the data (or row, to match the other's length) becomes a line object holding XData, YData and ZData, coloured from the axes' ColorOrder in turn. semilogx, semilogy and loglog set XScale or YScale to 'log'. The page draws each line through its points, a NaN breaking it.
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
    Python: graphics.py and datafun.py. The edges as histcounts chooses them (Scott's rule rounded to 1, 2 or 5 times a power of ten, or the number of bins, width, edges or limits given), the counts by histcounts' code, and the values normalised as asked ('count', 'probability', 'pdf', 'countdensity', 'cumcount' or 'cdf'); the page draws them as bars.
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
    Python: graphics.py. A quiver series of the arrows, scaled so that the longest is 0.9 (or the scale given) of the grid spacing, sqrt(dx*dy) on a grid; a scale of 0 draws them as they are.
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
    Python: colormaps.py. m-by-3 arrays of RGB values, 256 rows unless m is given. gray, hot, cool, spring, summer, autumn, winter, bone, copper and pink are their usual formulas in r = linspace(0, 1, m) (hot ramps red, then green, then blue; bone and pink mix gray with hot); jet interpolates between dark blue, blue, cyan, yellow, red and dark red; hsv steps round the hue circle by Python's colorsys.hsv_to_rgb; lines, prism and flag repeat their colours; colorcube takes the points of an RGB grid. parula, viridis and turbo interpolate linearly between anchor colours (parula's are this page's own blue-to-yellow ramp).
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
