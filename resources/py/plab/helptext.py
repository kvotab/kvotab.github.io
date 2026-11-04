"""One-line descriptions and the call forms of the builtins and keywords,
for help NAME and the Help panel: name -> (summary, [call forms], notes).

The table is written below as text: a line `name: summary` starts an entry,
the lines indented under it are its call forms, and an indented line that
starts with `* ` is a note."""

_TEXT = r'''
# ---- the language --------------------------------------------------------------------------
if: Run a block when a condition holds, with optional elseif and else branches.
    if condition, statements, end
    if condition, statements, elseif other, statements, else, statements, end
    * A condition holds when it is nonempty and every element is nonzero.
for: Repeat a block once for each column of an array.
    for k = first:last, statements, end
    for k = first:step:last, statements, end
    for column = A, statements, end
while: Repeat a block for as long as a condition holds.
    while condition, statements, end
switch: Pick a block by comparing a value with cases (numbers or text).
    switch value, case a, statements, case {b, c}, statements, otherwise, statements, end
try: Run a block, and another block if the first one throws an error.
    try, statements, catch, statements, end
    try, statements, catch err, statements, end
    * err is an MException: err.message, err.identifier and err.stack say what went wrong.
function: Start a function: in a function file, or after the code of a script file.
    function y = name(x)
    function [a, b] = name(x, y)
    function name(varargin)
    * Each function ends with end (or the next function line, when no function in the file has an end).
    * An arguments block at its top checks the inputs: arguments, then a line for each (x (1,:) double {mustBePositive} = 1: a size, a class and validators, each optional, and a default), then end. A value is converted to the class when it can be (a number to another kind, text to char or string), a scalar spread to a fixed size and a vector turned the way asked; a validator named alone takes the value, one written as a call (mustBeLessThan(n, 10)) runs as written. Lines opts.Name (with defaults) declare name-value arguments: the last parameter, opts, gathers them as a struct, given as Name=value or 'Name', value, the names matched without regard to case.
end: Close a block (if, for, while, switch, try, function); inside an index, the last index.
    A(end), A(end-1, :), x(end+1) = value
elseif: Another condition of an if block, tried when the ones before it fail.
    if a, ..., elseif b, ..., end
else: The branch of an if block taken when no condition holds.
    if a, ..., else, ..., end
case: A value (or a cell of values) that a switch block compares with.
    switch x, case 1, ..., case {2, 3}, ..., end
otherwise: The branch of a switch block taken when no case matches.
    switch x, case 1, ..., otherwise, ..., end
catch: The part of a try block that runs when the try part throws an error.
    try, ..., catch err, ..., end
parfor: A for loop whose passes run in parallel, on the workers of a pool.
    parfor k = 1:n, statements, end
    parfor (k = 1:n, M), statements, end
    * The pool starts with the first parfor if there is none (see parpool). The passes run in blocks on the workers, in no set order, and the results are put together in the order of the passes: what the loop gives run one pass at a time.
    * A variable read and never set in the loop goes to every worker. One indexed by k in one subscript, the same way wherever it appears (y(k), A(:, k), c{k}), is a slice each pass sets for itself. One set only as s = s + e (or - .* * & |, [s, e], [s; e], min, max) is reduced. One set in a pass before it is read there belongs to that pass.
    * A loop that does not keep to that (a pass reading what another pass set), or that has break, return, eval, load without an output, clear or global variables, runs one pass at a time, and a warning says why. So does parfor (k = 1:n, 0); M limits the workers it uses.
    * The workers get the files of the current folder and the program files of the path, and the files the passes write come back. Figures, input() and breakpoints stay here: the passes cannot use them.
spmd: A block for parallel workers; here its body runs once.
    spmd, statements, end
    * Inside it labindex (spmdIndex) is 1 and numlabs (spmdSize) is 1.
labindex: In an spmd block, the worker's number: 1 here, where the block runs once (as spmdIndex).
    k = labindex
spmdIndex: In an spmd block, the worker's number: 1 here, where the block runs once.
    k = spmdIndex
numlabs: In an spmd block, the number of workers: 1 here (as spmdSize).
    n = numlabs
spmdSize: In an spmd block, the number of workers: 1 here.
    n = spmdSize
parpool: Start a pool of workers for parfor loops.
    parpool
    parpool(n)
    p = parpool(...)
    * Without n the pool has a worker for each processor core but one, at most 8. Each worker is a Python engine of its own in this tab: it takes a few seconds to start and holds memory of its own. delete(gcp) stops the pool.
gcp: The pool of workers, started if there is none.
    p = gcp
    p = gcp('nocreate')
    * p.NumWorkers is its number of workers; with 'nocreate', [] when there is no pool. delete(p) stops the pool.
getCurrentTask: On a worker of the pool, its task (t.ID is the worker's number); [] elsewhere.
    t = getCurrentTask()
enumeration: The members of an enumeration class (a class with an enumeration block).
    enumeration ClassName
    m = enumeration('ClassName')
    [m, names] = enumeration(obj)
    * classdef Color, enumeration, Red, Green, end, end makes Color.Red and Color.Green, each one object: == and ~= compare members (or a member and its name as text), switch and ismember take them, char, string and cellstr give their names. Members may be given values for the constructor (Mon (1)), and a class based on a number class (classdef Level < uint8) has members that are those numbers: uint8(Level.High), Level.High > Level.Low, Level.High + 1.
import: Let a function or the Command Window call a package's functions and classes by their short names.
    import pkg.*
    import pkg.name
    import pkg.sub.*
    list = import
    * A package is a folder whose name starts with + (+pkg/f.m is pkg.f; +pkg/+sub/g.m is pkg.sub.g; +pkg/Cls.m or +pkg/@Cls/Cls.m is the class pkg.Cls). An import in a function lasts for that call, one in the Command Window until it is restarted.
classdef: A class of your own, in a file of its name: properties, methods and events.
    classdef Name
    classdef Name < handle
    classdef Name < Super1 & Super2
    properties (Access = private, Constant, Dependent) ... end
    methods (Static, Access = private) ... end
    events ... end
    * Property lines are Name, or Name = default, with a size and class that may be given (Balance (1,1) double = 0). The constructor is the method named as the class (function obj = Name(args)); the object is its output, there already with its defaults. A subclass of handle is shared by every variable that holds it; any other class is a value, copied when a copy changes, so a method that changes it returns it (obj = scale(obj, 2)). Methods are called as obj.method(args) or method(obj, args); a Static method as Name.method(args), a Constant property as Name.Prop. get.Prop and set.Prop methods run when a property is read or set (a Dependent property has only them). A method named as an operator's function (plus, minus, times, mtimes, eq, lt, uminus, ...) or as a builtin (disp, norm, size, ...) takes its place for the class's objects. obj@Super(args) calls the superclass constructor, method@Super(obj, args) its method. Events are raised by notify and heard through addlistener. delete(obj) runs the class's delete method and leaves the object invalid (isvalid). A property's size, class and validators (s (1,1) double {mustBePositive}) are checked whenever it is set. An enumeration block makes the class an enumeration (see enumeration).
break: Leave the innermost for or while loop.
    break
continue: Go on with the next pass of the innermost for or while loop.
    continue
return: Leave the function (or script) here.
    return
global: Share a variable between functions and the base workspace.
    global name1 name2
persistent: Keep a variable of a function between its calls.
    persistent name1 name2
    * A persistent variable starts as [] the first time.

# ---- making arrays ---------------------------------------------------------------------------
zeros: An array of zeros.
    Z = zeros(n)
    Z = zeros(m, n, ...)
    Z = zeros([m n ...])
    Z = zeros(..., classname)
    Z = zeros(..., 'like', p)
ones: An array of ones.
    X = ones(n)
    X = ones(m, n, ...)
    X = ones(..., classname)
eye: The identity matrix: ones on the diagonal, zeros elsewhere.
    I = eye(n)
    I = eye(m, n)
    I = eye(..., classname)
rand: Random numbers drawn evenly from the open interval (0, 1).
    X = rand
    X = rand(n)
    X = rand(m, n, ...)
    X = rand(..., 'single')
    * The generator is a Mersenne Twister; rng sets its seed.
randn: Random numbers from the standard normal distribution (mean 0, standard deviation 1).
    X = randn(n)
    X = randn(m, n, ...)
randi: Random integers drawn evenly from a range.
    X = randi(imax)
    X = randi(imax, m, n)
    X = randi([imin imax], m, n)
randperm: A random permutation of 1 to n.
    p = randperm(n)
    p = randperm(n, k)
rng: Seed the random number generator, or read and restore its state.
    rng(seed)
    rng('default')
    rng('shuffle')
    s = rng
    rng(s)
linspace: Points evenly spaced between two values, both ends included.
    y = linspace(a, b)
    y = linspace(a, b, n)
    * Without n, 100 points.
logspace: Points evenly spaced in the exponent, from 10^a to 10^b.
    y = logspace(a, b)
    y = logspace(a, b, n)
colon: The colon operator as a function.
    v = colon(a, b)
    v = colon(a, step, b)
magic: A magic square: its rows, columns and both diagonals have the same sum.
    M = magic(n)
diag: Make a diagonal matrix from a vector, or take a diagonal of a matrix.
    D = diag(v)
    D = diag(v, k)
    d = diag(A)
    d = diag(A, k)
repmat: Repeat an array as tiles.
    B = repmat(A, n)
    B = repmat(A, m, n, ...)
    B = repmat(A, [m n ...])
reshape: The same elements, in the same column order, in another shape.
    B = reshape(A, m, n, ...)
    B = reshape(A, [m n ...])
    B = reshape(A, m, [])
cat: Join arrays along a dimension.
    C = cat(dim, A, B, ...)
horzcat: Join arrays side by side, as [A, B] does.
    C = horzcat(A, B, ...)
vertcat: Join arrays one under the other, as [A; B] does.
    C = vertcat(A, B, ...)
meshgrid: Coordinate arrays for a grid: x varies along the rows, y down the columns.
    [X, Y] = meshgrid(x, y)
    [X, Y] = meshgrid(x)
    [X, Y, Z] = meshgrid(x, y, z)
ndgrid: Coordinate arrays for a grid, in the order of the dimensions (the first input varies down the columns).
    [X1, X2] = ndgrid(x1, x2)
    [X1, X2, X3] = ndgrid(x1, x2, x3)
true: Logical true, or an array of it.
    t = true
    T = true(m, n)
false: Logical false, or an array of it.
    f = false
    F = false(m, n)
pi: The ratio of a circle's circumference to its diameter.
    p = pi
eps: The distance from a number to the next larger floating-point number.
    e = eps
    d = eps(x)
    e = eps('single')
    * eps alone is 2^-52, the spacing at 1.
Inf: Positive infinity (-Inf for negative), or an array of it.
    x = Inf
    X = Inf(m, n)
inf: Positive infinity; the same as Inf.
    x = inf
NaN: Not-a-Number, the result of an undefined operation such as 0/0, or an array of it.
    x = NaN
    X = NaN(m, n)
    * NaN is never equal to anything, itself included: test with isnan.
nan: Not-a-Number; the same as NaN.
    x = nan
i: The imaginary unit, the square root of -1.
    z = 3 + 4i
    z = complex(3, 4)
    * Write 4i or 4*1i rather than 4*i when i may be a variable.
j: The imaginary unit; the same as i.
    z = 3 + 4j
intmax: The largest value an integer class holds.
    v = intmax
    v = intmax(classname)
intmin: The smallest value an integer class holds.
    v = intmin
    v = intmin(classname)
realmax: The largest finite floating-point number.
    v = realmax
    v = realmax('single')
realmin: The smallest positive normalized floating-point number.
    v = realmin
    v = realmin('single')
flintmax: The largest integer up to which floating point holds every integer exactly (2^53 for double).
    v = flintmax
    v = flintmax('single')
blkdiag: A block diagonal matrix built from the matrices given.
    B = blkdiag(A1, A2, ...)
toeplitz: A Toeplitz matrix: constant along each diagonal.
    T = toeplitz(c, r)
    T = toeplitz(r)
hankel: A Hankel matrix: constant along each anti-diagonal.
    H = hankel(c)
    H = hankel(c, r)
vander: The Vandermonde matrix of a vector: its columns are powers of the vector.
    V = vander(v)
hilb: The Hilbert matrix, H(i,j) = 1/(i+j-1), a classic ill-conditioned matrix.
    H = hilb(n)
invhilb: The exact inverse of the Hilbert matrix.
    H = invhilb(n)
pascal: The Pascal matrix: binomial coefficients, symmetric and positive definite.
    P = pascal(n)
compan: The companion matrix of a polynomial; its eigenvalues are the polynomial's roots.
    C = compan(p)
wilkinson: Wilkinson's eigenvalue test matrix.
    W = wilkinson(n)
rosser: Rosser's 8-by-8 eigenvalue test matrix.
    R = rosser
accumarray: Gather values by index and combine those that share one (a sum by default).
    A = accumarray(subs, vals)
    A = accumarray(subs, vals, sz)
    A = accumarray(subs, vals, sz, fun)
    A = accumarray(subs, vals, sz, fun, fillval)
    A = accumarray({i, j, k}, vals, ...)
    * subs is a matrix with a column for each dimension, a column of linear indices, or a cell of index vectors. A fun that returns logical values or cells makes a logical or cell array.

# ---- size and shape --------------------------------------------------------------------------
size: The length of each dimension.
    sz = size(A)
    n = size(A, dim)
    [m, n] = size(A)
    [m, n, p, ...] = size(A)
numel: The number of elements.
    n = numel(A)
length: The length of the largest dimension (0 for an empty array).
    n = length(A)
ndims: The number of dimensions (always 2 or more).
    n = ndims(A)
isempty: True when an array has no elements.
    tf = isempty(A)
isscalar: True for a 1-by-1 array.
    tf = isscalar(A)
isvector: True for a 1-by-n or n-by-1 array.
    tf = isvector(A)
isrow: True for a 1-by-n array.
    tf = isrow(A)
iscolumn: True for an n-by-1 array.
    tf = iscolumn(A)
ismatrix: True for an array of two dimensions.
    tf = ismatrix(A)
issquare: True for an n-by-n array.
    tf = issquare(A)
squeeze: Remove the dimensions of length 1 (beyond the first two).
    B = squeeze(A)
permute: Rearrange the dimensions of an array.
    B = permute(A, order)
shiftdim: Shift the dimensions of an array.
    B = shiftdim(A, n)
    [B, n] = shiftdim(A)
    * n > 0 moves the first n dimensions to the end; n < 0 puts -n singleton dimensions in front. With no n, the leading singleton dimensions are taken away and their number is the second output (a row vector becomes a column).
ipermute: Undo a permute.
    A = ipermute(B, order)
circshift: Shift elements around in a circle.
    B = circshift(A, k)
    B = circshift(A, k, dim)
    B = circshift(A, [k1 k2])
flip: Reverse the order of elements along a dimension.
    B = flip(A)
    B = flip(A, dim)
fliplr: Reverse the order of the columns.
    B = fliplr(A)
flipud: Reverse the order of the rows.
    B = flipud(A)
rot90: Turn a matrix by multiples of 90 degrees, anticlockwise.
    B = rot90(A)
    B = rot90(A, k)
tril: The lower triangle of a matrix, the rest set to zero.
    L = tril(A)
    L = tril(A, k)
triu: The upper triangle of a matrix, the rest set to zero.
    U = triu(A)
    U = triu(A, k)
pagemtimes: Each page of X (its first two dimensions) times the matching page of Y.
    Z = pagemtimes(X, Y)
    Z = pagemtimes(X, transpX, Y, transpY)
    * transpX and transpY are 'none', 'transpose' or 'ctranspose'. Pages of size 1 in a dimension are used against all of the other's.
pagetranspose: Each page (the first two dimensions) turned.
    B = pagetranspose(A)
pagectranspose: Each page turned and its complex numbers conjugated.
    B = pagectranspose(A)
tensorprod: Products of A and B summed over dimensions of each.
    C = tensorprod(A, B, dimA, dimB)
    C = tensorprod(A, B, dims)
    C = tensorprod(A, B)
    C = tensorprod(A, B, 'all')
    * The result has A's other dimensions, then B's. With no dimensions it is the outer product; with 'all', the sum of all of A.*B.
kron: The Kronecker product: every element of A times the whole of B.
    K = kron(A, B)
sub2ind: Linear indices from subscripts.
    ind = sub2ind(sz, row, col)
    ind = sub2ind(sz, i1, i2, i3, ...)
ind2sub: Subscripts from linear indices.
    [row, col] = ind2sub(sz, ind)
    [i1, i2, i3, ...] = ind2sub(sz, ind)
find: The indices of the nonzero elements.
    k = find(X)
    k = find(X, n)
    k = find(X, n, 'last')
    [row, col] = find(X)
    [row, col, v] = find(X)
nnz: The number of nonzero elements.
    n = nnz(X)
nonzeros: The nonzero elements, as a column, in column order.
    v = nonzeros(X)

# ---- arithmetic ------------------------------------------------------------------------------
plus: Addition, A + B, element by element.
    C = plus(A, B)
minus: Subtraction, A - B, element by element.
    C = minus(A, B)
times: Multiplication element by element, A .* B.
    C = times(A, B)
rdivide: Division element by element, A ./ B.
    C = rdivide(A, B)
ldivide: Left division element by element, A .\ B (B divided by A).
    C = ldivide(A, B)
mtimes: Matrix multiplication, A * B.
    C = mtimes(A, B)
mrdivide: Right matrix division, A / B, the solution of x*B = A.
    x = mrdivide(A, B)
mldivide: Left matrix division, A \ b, the solution of A*x = b (least squares when A is not square).
    x = mldivide(A, b)
    * A square matrix that is close to singular gives a warning with its reciprocal condition number.
power: Power element by element, A .^ B.
    C = power(A, B)
mpower: Matrix power, A ^ p.
    C = mpower(A, p)
uminus: Negation, -A.
    B = uminus(A)
uplus: Unary plus, +A.
    B = uplus(A)
transpose: Transpose without conjugating, A.'.
    B = transpose(A)
ctranspose: Complex conjugate transpose, A'.
    B = ctranspose(A)
abs: The absolute value; the modulus of a complex number.
    y = abs(x)
sign: -1, 0 or 1 by the sign of each element (x./abs(x) for complex x).
    s = sign(x)
sqrt: The square root (complex for negative numbers).
    y = sqrt(x)
nthroot: The real nth root, negative for a negative number and odd n.
    y = nthroot(x, n)
hypot: sqrt(a.^2 + b.^2), without overflow or underflow on the way.
    c = hypot(a, b)
exp: The exponential, e^x.
    y = exp(x)
    d = exp(-tau*s)
    * Of tf('s') times -tau: a pure delay of tau.
expm1: exp(x) - 1, accurate for small x.
    y = expm1(x)
log: The natural logarithm (complex for negative numbers); or, with a test case, a message logged by a test.
    y = log(x)
    log(testCase, diagnostic)
    log(testCase, level, diagnostic)
    * With a test case first: a message shown as the test runs, as [Logged] text, when the run's OutputDetail is at least level (1 to 4, 2 when not given).
log1p: log(1 + x), accurate for small x.
    y = log1p(x)
log2: The base 2 logarithm, or a number split into mantissa and exponent.
    y = log2(x)
    [f, e] = log2(x)
log10: The base 10 logarithm.
    y = log10(x)
pow2: Powers of 2, or f times 2^e.
    y = pow2(e)
    y = pow2(f, e)
nextpow2: The exponent of the next power of 2 at or above abs(x).
    p = nextpow2(x)
floor: Round toward minus infinity.
    y = floor(x)
ceil: Round toward plus infinity.
    y = ceil(x)
round: Round to the nearest integer (halves away from zero), or to a number of digits.
    y = round(x)
    y = round(x, n)
    y = round(x, n, 'significant')
fix: Round toward zero.
    y = fix(x)
mod: The remainder after division, with the sign of the divisor: mod(a, b) = a - floor(a./b).*b.
    r = mod(a, b)
rem: The remainder after division, with the sign of the dividend: rem(a, b) = a - fix(a./b).*b.
    r = rem(a, b)
idivide: Integer division with a chosen rounding.
    c = idivide(a, b)
    c = idivide(a, b, 'fix' | 'round' | 'floor' | 'ceil')
bitand: The bits set in both inputs.
    c = bitand(a, b)
    c = bitand(a, b, assumedtype)
    * Integers keep their class; doubles must be whole numbers in the range of assumedtype (uint64 unless named), and the result is double.
    * The inputs expand to one size, as in arithmetic.
bitor: The bits set in either input.
    c = bitor(a, b)
    c = bitor(a, b, assumedtype)
bitxor: The bits set in one input but not both.
    c = bitxor(a, b)
    c = bitxor(a, b, assumedtype)
bitshift: Bits moved left (k > 0) or right (k < 0).
    c = bitshift(a, k)
    c = bitshift(a, k, assumedtype)
    * Bits moved past the top of the type are lost; a right shift rounds down, a signed value keeping its sign.
bitcmp: Every bit turned round.
    c = bitcmp(a)
    c = bitcmp(a, assumedtype)
    c = bitcmp(a, n)
    * bitcmp(a, n) turns the lowest n bits of a whole number.
bitget: The bit (1 or 0) at a position, 1 the lowest.
    b = bitget(a, bit)
    * bitget(x, 1:8) gives the eight lowest bits of a scalar, lowest first.
bitset: A bit set to 1, or to v.
    c = bitset(a, bit)
    c = bitset(a, bit, v)
gcd: The greatest common divisor.
    g = gcd(a, b)
lcm: The least common multiple.
    m = lcm(a, b)
factorial: n!, the product of 1 to n.
    f = factorial(n)
nchoosek: The binomial coefficient, or every combination of k elements of a vector.
    c = nchoosek(n, k)
    C = nchoosek(v, k)
primes: The prime numbers up to n.
    p = primes(n)
    * In the class of n.
isprime: True for the prime numbers.
    tf = isprime(n)
factor: The prime factors of an integer.
    f = factor(n)
perms: Every permutation of a vector's elements, one per row.
    P = perms(v)
rat: A rational approximation, as text or as numerator and denominator.
    s = rat(x)
    [n, d] = rat(x)
    [n, d] = rat(x, tol)
rats: Rational approximations as text, in columns.
    s = rats(x)
reallog: The natural logarithm, with an error for a negative or complex number.
    y = reallog(x)
realpow: Power, with an error when the result would be complex.
    y = realpow(a, b)
realsqrt: The square root, with an error for a negative or complex number.
    y = realsqrt(x)

# ---- trigonometry ----------------------------------------------------------------------------
sin: The sine of angles in radians.
    y = sin(x)
cos: The cosine of angles in radians.
    y = cos(x)
tan: The tangent of angles in radians.
    y = tan(x)
sec: The secant, 1/cos(x), of angles in radians.
    y = sec(x)
csc: The cosecant, 1/sin(x), of angles in radians.
    y = csc(x)
cot: The cotangent, 1/tan(x), of angles in radians.
    y = cot(x)
asin: The inverse sine, in radians.
    y = asin(x)
acos: The inverse cosine, in radians.
    y = acos(x)
atan: The inverse tangent, in radians, between -pi/2 and pi/2.
    y = atan(x)
atan2: The angle of the point (x, y), in radians between -pi and pi.
    theta = atan2(y, x)
asec: The inverse secant, in radians.
    y = asec(x)
acsc: The inverse cosecant, in radians.
    y = acsc(x)
acot: The inverse cotangent, in radians.
    y = acot(x)
sinh: The hyperbolic sine.
    y = sinh(x)
cosh: The hyperbolic cosine.
    y = cosh(x)
tanh: The hyperbolic tangent.
    y = tanh(x)
sech: The hyperbolic secant.
    y = sech(x)
csch: The hyperbolic cosecant.
    y = csch(x)
coth: The hyperbolic cotangent.
    y = coth(x)
asinh: The inverse hyperbolic sine.
    y = asinh(x)
acosh: The inverse hyperbolic cosine.
    y = acosh(x)
atanh: The inverse hyperbolic tangent.
    y = atanh(x)
asech: The inverse hyperbolic secant.
    y = asech(x)
acsch: The inverse hyperbolic cosecant.
    y = acsch(x)
acoth: The inverse hyperbolic cotangent.
    y = acoth(x)
sind: The sine of angles in degrees (exactly 0 at multiples of 180).
    y = sind(x)
cosd: The cosine of angles in degrees (exactly 0 at odd multiples of 90).
    y = cosd(x)
tand: The tangent of angles in degrees.
    y = tand(x)
secd: The secant of angles in degrees.
    y = secd(x)
cscd: The cosecant of angles in degrees.
    y = cscd(x)
cotd: The cotangent of angles in degrees.
    y = cotd(x)
asind: The inverse sine, in degrees.
    y = asind(x)
acosd: The inverse cosine, in degrees.
    y = acosd(x)
atand: The inverse tangent, in degrees.
    y = atand(x)
asecd: The inverse secant, in degrees.
    y = asecd(x)
acscd: The inverse cosecant, in degrees.
    y = acscd(x)
acotd: The inverse cotangent, in degrees.
    y = acotd(x)
atan2d: The angle of the point (x, y), in degrees between -180 and 180.
    theta = atan2d(y, x)
sinpi: sin(pi*x), exact at the integers.
    y = sinpi(x)
cospi: cos(pi*x), exact at the half-integers.
    y = cospi(x)
deg2rad: Degrees to radians.
    r = deg2rad(d)
rad2deg: Radians to degrees.
    d = rad2deg(r)

# ---- complex numbers -------------------------------------------------------------------------
real: The real part.
    x = real(z)
imag: The imaginary part.
    y = imag(z)
conj: The complex conjugate.
    w = conj(z)
angle: The phase angle of a complex number, in radians between -pi and pi.
    theta = angle(z)
complex: A complex number from its real and imaginary parts (kept complex when the imaginary part is 0).
    z = complex(a, b)
    z = complex(a)
isreal: True when an array is stored without imaginary parts.
    tf = isreal(A)
cplxpair: Sort complex numbers into conjugate pairs, the real ones last.
    B = cplxpair(A)
    B = cplxpair(A, tol)
    B = cplxpair(A, tol, dim)
    * Pairs by increasing real part, the one with negative imaginary part first; each column of a matrix (or along dim). Numbers that cannot be paired are an error.
unwrap: Remove the jumps of 2*pi from a sequence of phase angles.
    q = unwrap(p)
    q = unwrap(p, tol)
    q = unwrap(p, tol, dim)

# ---- comparison and logic --------------------------------------------------------------------
eq: Equality element by element, A == B.
    tf = eq(A, B)
ne: Inequality element by element, A ~= B.
    tf = ne(A, B)
lt: Less than, A < B.
    tf = lt(A, B)
gt: Greater than, A > B.
    tf = gt(A, B)
le: Less than or equal, A <= B.
    tf = le(A, B)
ge: Greater than or equal, A >= B.
    tf = ge(A, B)
and: Logical AND element by element, A & B.
    tf = and(A, B)
or: Logical OR element by element, A | B.
    tf = or(A, B)
not: Logical NOT, ~A.
    tf = not(A)
xor: Logical exclusive OR: true where exactly one of the two is nonzero.
    tf = xor(A, B)
isequal: True when the arrays have the same size and values (NaN is never equal).
    tf = isequal(A, B, ...)
isequaln: Like isequal, with NaN equal to NaN.
    tf = isequaln(A, B, ...)
isnan: True for NaN elements.
    tf = isnan(A)
ismissing: True for missing elements: NaN, <missing> strings, blanks in a char array, empty text in a cell, NaT, undefined categories.
    tf = ismissing(A)
    tf = ismissing(T)
    * For a table, each variable's elements side by side: a logical array of the table's rows and of its variables' columns.
isinf: True for Inf and -Inf elements.
    tf = isinf(A)
isfinite: True for elements that are neither Inf nor NaN.
    tf = isfinite(A)
any: True when any element is nonzero, along a dimension.
    tf = any(A)
    tf = any(A, dim)
    tf = any(A, 'all')
all: True when every element is nonzero, along a dimension.
    tf = all(A)
    tf = all(A, dim)
    tf = all(A, 'all')

# ---- data analysis ---------------------------------------------------------------------------
sum: The sum of the elements, down the columns by default.
    S = sum(A)
    S = sum(A, dim)
    S = sum(A, 'all')
    S = sum(..., 'omitnan')
prod: The product of the elements, down the columns by default.
    P = prod(A)
    P = prod(A, dim)
cumsum: Cumulative sums.
    B = cumsum(A)
    B = cumsum(A, dim)
    B = cumsum(..., 'reverse')
cumprod: Cumulative products.
    B = cumprod(A)
    B = cumprod(A, dim)
cummax: The largest element so far.
    M = cummax(A)
    M = cummax(A, dim)
cummin: The smallest element so far.
    M = cummin(A)
    M = cummin(A, dim)
diff: Differences between neighbours, or the nth differences.
    D = diff(X)
    D = diff(X, n)
    D = diff(X, n, dim)
mean: The average.
    M = mean(A)
    M = mean(A, dim)
    M = mean(A, vecdim)
    M = mean(A, 'all')
    M = mean(..., 'omitnan')
    M = mean(..., 'Weights', w)
    M = mean(..., outtype)
    * outtype is 'default', 'double' or 'native'. w is a vector along the dimension or an array the size of A. The sum is taken in double, so a long single array keeps its precision.
    m = mean(pd)
    * mean(pd) is the mean of a distribution object (makedist, fitdist); so too median, std, var and iqr.
median: The middle value.
    M = median(A)
    M = median(A, dim)
    M = median(A, vecdim)
    M = median(A, 'all')
    M = median(..., 'omitnan')
    M = median(..., outtype)
    * Integers and logicals keep their class (two middle integers averaged and rounded) unless outtype is 'default' or 'double'; single stays single. Complex values are ordered by size, then angle.
    m = median(pd)
mode: The most frequent value (the smallest of those tied).
    M = mode(A)
    M = mode(A, dim)
    M = mode(A, vecdim)
    M = mode(A, 'all')
    [M, F] = mode(...)
    [M, F, C] = mode(...)
std: The standard deviation (normalized by N-1, or N with w = 1).
    s = std(A)
    s = std(A, w)
    s = std(A, w, dim)
    s = std(A, w, vecdim)
    [s, M] = std(...)
    s = std(..., 'omitnan')
    s = std(pd)
var: The variance (normalized by N-1, or N with w = 1).
    v = var(A)
    v = var(A, w)
    v = var(A, w, dim)
    v = var(A, w, vecdim)
    v = var(A, 'all')
    v = var(..., 'omitnan')
    [v, M] = var(...)
    * w is 0 (N-1), 1 (N), or weights: a vector along the dimension or an array the size of A. M is the mean the variance is about (weighted with the weights). vecdim works over several dimensions at once.
    v = var(pd)
min: The smallest elements, or the smaller of two arrays element by element.
    m = min(A)
    m = min(A, [], dim)
    [m, k] = min(A)
    C = min(A, B)
    m = min(A, [], 'all')
    * NaN is left out unless every element is NaN.
max: The largest elements, or the larger of two arrays element by element.
    m = max(A)
    m = max(A, [], dim)
    [m, k] = max(A)
    C = max(A, B)
    m = max(A, [], 'all')
    * NaN is left out unless every element is NaN.
bounds: The smallest and largest elements.
    [lo, hi] = bounds(A)
    [lo, hi] = bounds(A, dim)
range: The difference between the largest and smallest elements.
    r = range(A)
    r = range(A, dim)
sort: Sort the elements, down the columns by default.
    B = sort(A)
    B = sort(A, dim)
    B = sort(..., 'descend')
    [B, I] = sort(...)
    * Text sorts too: a cell array of char vectors, or a string array.
sortrows: Sort the rows of a matrix by its columns, or of a table by its variables.
    B = sortrows(A)
    B = sortrows(A, column)
    B = sortrows(A, -column)
    T2 = sortrows(T, vars)
    T2 = sortrows(T, vars, direction)
    [B, I] = sortrows(...)
    * For a table, vars are names or positions (negative for descending), or the row names' or row times' dimension name; direction 'ascend' or 'descend', one for each variable or for all.
issorted: True when the elements are in sorted order.
    tf = issorted(A)
unique: The distinct values, sorted (or in the order first met).
    C = unique(A)
    C = unique(A, 'stable')
    C = unique(A, 'rows')
    [C, ia, ic] = unique(...)
    * For a table, its distinct rows.
ismember: Which elements of A are found in B, and where.
    tf = ismember(A, B)
    [tf, loc] = ismember(A, B)
    tf = ismember(A, B, 'rows')
    * Two tables of the same variables are compared row by row.
union: The values in either set.
    C = union(A, B)
    [C, ia, ib] = union(A, B)
intersect: The values in both sets.
    C = intersect(A, B)
    [C, ia, ib] = intersect(A, B)
setdiff: The values of A that are not in B.
    C = setdiff(A, B)
    [C, ia] = setdiff(A, B)
setxor: The values in one set but not both.
    C = setxor(A, B)
histcounts: Counts of values in bins.
    [N, edges] = histcounts(X)
    [N, edges] = histcounts(X, nbins)
    [N, edges] = histcounts(X, edges)
    [N, edges, bin] = histcounts(...)
histc: Counts of values between edges (the last bin holds values equal to the last edge).
    n = histc(x, edges)
    [n, bin] = histc(x, edges)
discretize: The bin each value falls into.
    Y = discretize(X, edges)
    Y = discretize(X, n)
cov: The covariance of two vectors, or of the columns of a matrix.
    C = cov(A)
    C = cov(x, y)
    C = cov(..., w)
    C = cov(..., 'omitrows')
    * w 0 (the default) normalizes by N - 1, 1 by N; a vector of weights, one per row, by their sum. 'partialrows' takes each pair of columns from the rows both have.
corrcoef: Correlation coefficients.
    R = corrcoef(A)
    R = corrcoef(x, y)
    [R, P] = corrcoef(...)
trapz: An integral by the trapezoidal rule.
    Q = trapz(y)
    Q = trapz(x, y)
    Q = trapz(..., dim)
    * x is a scalar spacing, the points along the dimension, or an array the size of y. Of two arguments, a scalar second one is the dimension.
cumtrapz: The running integral by the trapezoidal rule.
    Q = cumtrapz(y)
    Q = cumtrapz(x, y)
    Q = cumtrapz(..., dim)
quantile: Quantiles of a sample.
    Q = quantile(X, p)
    Q = quantile(X, p, dim)
    Q = quantile(X, p, vecdim)
    Q = quantile(X, p, 'all')
    * Of a vector, the quantiles are laid out as p is. Along dimensions, they take the place of the first one; 'all' gives a column.
prctile: Percentiles of a sample.
    P = prctile(X, p)
    P = prctile(X, p, dim)
iqr: The interquartile range.
    r = iqr(X)
    r = iqr(pd)
skewness: The sample skewness.
    s = skewness(X)
    s = skewness(X, flag)
kurtosis: The sample kurtosis (3 for a normal distribution).
    k = kurtosis(X)
    k = kurtosis(X, flag)
movmean: The mean over a moving window.
    M = movmean(A, k)
    M = movmean(A, [kb kf])
    M = movmean(..., dim)
movsum: The sum over a moving window.
    M = movsum(A, k)
movmax: The largest element in a moving window.
    M = movmax(A, k)
movmin: The smallest element in a moving window.
    M = movmin(A, k)
movmedian: The median over a moving window.
    M = movmedian(A, k)
movstd: The standard deviation over a moving window.
    M = movstd(A, k)
    M = movstd(A, k, w, dim)
movvar: The variance over a moving window.
    M = movvar(A, k)
    M = movvar(A, k, w, dim)
movprod: The product over a moving window.
    M = movprod(A, k)
movmad: The median absolute deviation over a moving window.
    M = movmad(A, k)
    M = movmad(..., 'omitnan', 'Endpoints', 'discard')
rescale: Scale values linearly to fill [0, 1], or another interval.
    R = rescale(A)
    R = rescale(A, l, u)
    R = rescale(..., 'InputMin', inmin, 'InputMax', inmax)
    * l, u, inmin and inmax may be arrays that fit A (as row or column of bounds); values outside [inmin, inmax] are clamped first.
normalize: Centre and scale data (z-scores by default).
    N = normalize(A)
    N = normalize(A, dim)
    N = normalize(..., 'zscore', 'robust')
    N = normalize(..., 'norm', p)
    N = normalize(..., 'range', [a b])
    N = normalize(..., 'medianiqr')
    N = normalize(..., 'center', c, 'scale', s)
    [N, C, S] = normalize(...)

# ---- descriptive statistics ------------------------------------------------------------------
trimmean: The mean of the data left when a share of the smallest and the largest values is set aside.
    m = trimmean(X, percent)
    m = trimmean(X, percent, flag)
    m = trimmean(X, percent, flag, dim)
    * percent is the share set aside in all, half at each end: 20 leaves out the lowest 10% and the highest 10%. flag says what to do when that is not a whole number of values: 'round' (the default) rounds it, 'floor' rounds it down, 'weighted' gives the values on the edge partial weights.
geomean: The geometric mean: the nth root of the product of n values.
    m = geomean(X)
    m = geomean(X, dim)
    * The values must not be negative; a zero among them gives 0.
harmmean: The harmonic mean: the number of values divided by the sum of their reciprocals.
    m = harmmean(X)
    m = harmmean(X, dim)
mad: The mean absolute deviation from the mean, or the median absolute deviation from the median.
    d = mad(X)
    d = mad(X, flag)
    d = mad(X, flag, dim)
    d = mad(X, flag, 'all')
    * flag 0 (the default) gives mean(abs(X - mean(X))), flag 1 median(abs(X - median(X))). NaN values are left out.
moment: A central moment of a sample: the mean of (X - mean(X)).^order.
    m = moment(X, order)
    m = moment(X, order, dim)
    * The second is the variance normalized by N.
zscore: Standardized data: the values less their mean, divided by their standard deviation.
    Z = zscore(X)
    Z = zscore(X, flag)
    Z = zscore(X, flag, dim)
    [Z, mu, sigma] = zscore(...)
    * flag 1 normalizes the standard deviation by N instead of N-1. Values that are all the same give zeros.
nanmean: The mean of the values that are not NaN.
    m = nanmean(X)
    m = nanmean(X, dim)
nanmedian: The median of the values that are not NaN.
    m = nanmedian(X)
    m = nanmedian(X, dim)
nanstd: The standard deviation of the values that are not NaN.
    s = nanstd(X)
    s = nanstd(X, flag)
    s = nanstd(X, flag, dim)
nanvar: The variance of the values that are not NaN.
    v = nanvar(X)
    v = nanvar(X, flag)
    v = nanvar(X, flag, dim)
nansum: The sum of the values that are not NaN.
    s = nansum(X)
    s = nansum(X, dim)
nanmax: The largest values, NaN left out (as max does).
    m = nanmax(X)
    [m, i] = nanmax(X, [], dim)
nanmin: The smallest values, NaN left out (as min does).
    m = nanmin(X)
    [m, i] = nanmin(X, [], dim)
tabulate: How often each value occurs: the value, its count and its percentage.
    tabulate(x)
    T = tabulate(x)
    * For whole numbers from 1 up, every value from 1 to the largest is listed, those that do not occur with the count 0. For text (a cell of text, a char matrix or a string array) T is a cell array.
grp2idx: The groups of a grouping variable: a group number for each observation, and the groups' names.
    [g, names] = grp2idx(group)
    [g, names, levels] = grp2idx(group)
    * Numbers make groups in increasing order, text in the order it first appears. Missing values (NaN, empty text) get g = NaN.
grpstats: Statistics of each group of the data.
    means = grpstats(X, group)
    [s1, s2, ...] = grpstats(X, group, {'stat1', 'stat2', ...})
    [...] = grpstats(X, group, whichstats, 'Alpha', alpha)
    * The statistics: 'mean', 'sem' (the standard error of the mean), 'numel', 'gname' (the group's name), 'std', 'var', 'min', 'max', 'range', 'median', 'meanci' and 'predci' (intervals for the mean and for one more observation, 95% unless alpha is given). Each has a row for each group and a column for each column of X; NaN values are left out.
ecdf: The empirical distribution function of a sample, with confidence bounds.
    [f, x] = ecdf(y)
    [f, x, flo, fup] = ecdf(y)
    [...] = ecdf(y, 'Function', 'survivor' | 'cumulative hazard', 'Alpha', alpha)
    ecdf(y)
    * f(i) is the share of the data at or below x(i); x starts with the smallest value twice, so that f starts at 0. flo and fup are Greenwood's bounds. With no outputs the function is drawn as steps.
ksdensity: A kernel estimate of the density (or the distribution function) a sample comes from.
    [f, xi] = ksdensity(x)
    f = ksdensity(x, pts)
    [f, xi, bw] = ksdensity(..., 'Bandwidth', bw, 'Kernel', 'normal' | 'box' | 'triangle' | 'epanechnikov')
    [...] = ksdensity(..., 'Function', 'cdf' | 'survivor' | 'cumhazard' | 'icdf', 'Support', 'positive' | [lo hi], 'NumPoints', n)
    ksdensity(x)
    * Without pts the estimate is given at 100 points over the data and a little beyond. The bandwidth suits normal data (Silverman's rule with a robust spread, the median absolute deviation) unless it is given. A bounded support works on the log of the data (or its logit, between lo and hi). With no outputs the estimate is drawn.
corr: Correlations between the columns of matrices, with p-values.
    rho = corr(X)
    rho = corr(X, Y)
    [rho, p] = corr(..., 'Type', 'Pearson' | 'Spearman' | 'Kendall', 'Rows', 'all' | 'complete' | 'pairwise', 'Tail', 'both' | 'right' | 'left')
    * The p-values test for no correlation: from the t distribution for Pearson's and Spearman's, Kendall's own for Kendall's.
bootstrp: A statistic of samples drawn from the data with replacement.
    stats = bootstrp(nboot, @fun, data)
    stats = bootstrp(nboot, @fun, data1, data2, ...)
    [stats, samples] = bootstrp(...)
    * Each row of stats is fun of one sample, made into a row. The data must have the same number of rows (vectors the same length); the same rows are drawn from each. samples has the indices drawn, a column for each sample. The draws come from the generator that rng sets.
jackknife: A statistic of the data with each observation left out in turn.
    stats = jackknife(@fun, data)
    stats = jackknife(@fun, data1, data2, ...)
    * Row i of stats is fun of the data without row i.

# ---- probability distributions ---------------------------------------------------------------
makedist: A probability distribution object with the parameters given.
    pd = makedist(name)
    pd = makedist(name, 'param', value, ...)
    names = makedist
    * name: 'Normal', 'Lognormal', 'Exponential', 'Gamma', 'Weibull', 'Beta', 'Uniform', 'Poisson', 'Binomial', 'NegativeBinomial', 'ExtremeValue', 'GeneralizedExtremeValue', 'GeneralizedPareto', 'Rayleigh', 'Logistic', 'Loglogistic', 'InverseGaussian', 'Nakagami', 'Rician', 'BirnbaumSaunders', 'Burr', 'HalfNormal', 'tLocationScale', 'Triangular' or 'Loguniform'; makedist with no input lists them. Parameters left out keep their defaults (the Normal's mu 0 and sigma 1).
    * The object goes to pdf, cdf, icdf, random, mean, median, std, var, iqr, truncate and negloglik. Its parameters are its properties (pd.mu), as are ParameterValues, ParameterNames and DistributionName.
fitdist: A probability distribution object fitted to data.
    pd = fitdist(x, name)
    pd = fitdist(x, 'Kernel', 'Kernel', kernel, 'Bandwidth', bw)
    [pds, names] = fitdist(x, name, 'By', group)
    * Maximum likelihood estimates, except the Normal's and the Lognormal's sigma, which is the unbiased one that normfit gives. paramci(pd) gives the parameters' confidence intervals. With 'By' there is an object for each group, in a cell array.
mle: Maximum likelihood estimates of a distribution's parameters, with confidence intervals.
    phat = mle(x)
    [phat, pci] = mle(x, 'Distribution', name, 'Alpha', alpha)
    phat = mle(x, 'Distribution', 'Binomial', 'NTrials', n)
    * Without a distribution the data are taken to be normal. The normal sigma here is the likelihood's own, normalized by N. pci has the intervals' lower ends in its first row and their upper ends in its second.
pdf: The density of a distribution at x (the probabilities, for a discrete one).
    y = pdf(pd, x)
    y = pdf(name, x, A)
    y = pdf(name, x, A, B, C)
    y = pdf(gm, X)
    * pd is a distribution object (makedist, fitdist); name is a distribution's name ('Normal', 'Poisson', 't', ...) with its parameters in the order its own function takes them (normpdf(x, mu, sigma)).
    * pdf(gm, X) of a Gaussian mixture (gmdistribution): the mixture density at each row.
cdf: The cumulative distribution function of a distribution at x.
    p = cdf(pd, x)
    p = cdf(name, x, A, B, C)
    p = cdf(..., 'upper')
    * With 'upper', the probability above x.
icdf: The quantiles of a distribution: the inverse of its cdf.
    x = icdf(pd, p)
    x = icdf(name, p, A, B, C)
random: Random numbers from a distribution.
    r = random(pd)
    r = random(pd, m, n)
    r = random(name, A, B, C, m, n)
    Y = random(gm, n)
    [Y, compIdx] = random(gm, n)
    * The numbers come from the generator that rng sets.
    * random(gm, n) draws n rows from a Gaussian mixture; compIdx says which component each came from.
truncate: A distribution object limited to an interval, its probability there scaled up to 1.
    t = truncate(pd, lower, upper)
paramci: The confidence intervals of a fitted distribution object's parameters.
    ci = paramci(pd)
    ci = paramci(pd, 'Alpha', alpha)
    * A column for each parameter: the interval's lower end, then its upper end.
negloglik: The negative log-likelihood of a fitted distribution object for its data.
    nll = negloglik(pd)
normfit: The mean and the standard deviation of normal data, with confidence intervals.
    [muhat, sigmahat] = normfit(x)
    [muhat, sigmahat, muci, sigmaci] = normfit(x, alpha)
    * sigmahat is the sample standard deviation (normalized by N-1); the intervals come from the t and the chi-square distributions. A matrix gives estimates for each column.
unifit: The limits of uniform data (their smallest and largest values), with confidence intervals.
    [ahat, bhat] = unifit(x)
    [ahat, bhat, aci, bci] = unifit(x, alpha)
binofit: The probability of success from a count of successes in n trials, with an exact (Clopper-Pearson) interval.
    phat = binofit(x, n)
    [phat, pci] = binofit(x, n, alpha)
mvnpdf: The density of the multivariate normal distribution.
    y = mvnpdf(X)
    y = mvnpdf(X, mu, Sigma)
    * Each row of X is a point; mu is a row and Sigma the covariance matrix (a row gives a diagonal one). Left out: zero means and the identity matrix.
mvncdf: The multivariate normal distribution function: the probability below each row of X.
    p = mvncdf(X)
    p = mvncdf(X, mu, Sigma)
    * Computed by numerical integration (Genz's method), good to about 1e-5.
mvnrnd: Random vectors from the multivariate normal distribution.
    R = mvnrnd(mu, Sigma)
    R = mvnrnd(mu, Sigma, n)
    * Each row of R is one vector. Sigma may be singular (positive semidefinite).
mvtpdf: The density of the multivariate t distribution with correlation matrix C.
    y = mvtpdf(X, C, df)
mvtcdf: The multivariate t distribution function with correlation matrix C.
    p = mvtcdf(X, C, df)
mvtrnd: Random vectors from the multivariate t distribution with correlation matrix C.
    R = mvtrnd(C, df)
    R = mvtrnd(C, df, n)
randsample: A random sample of values, drawn without replacement unless asked.
    y = randsample(n, k)
    y = randsample(population, k)
    y = randsample(population, k, replace)
    y = randsample(population, k, replace, w)
    * randsample(n, k) draws k of the numbers 1 to n. w weights the values. The draws come from the generator that rng sets.
datasample: A random sample of the data: elements of a vector, or rows of a matrix.
    y = datasample(data, k)
    y = datasample(data, k, dim)
    [y, idx] = datasample(..., 'Replace', false, 'Weights', w)
    * With replacement unless 'Replace' is false; idx has the indices drawn.

# ---- hypothesis tests -------------------------------------------------------------------------
ttest: The one-sample or paired t-test: is the mean m (0 unless given)?
    h = ttest(x)
    h = ttest(x, m)
    h = ttest(x, y)
    [h, p, ci, stats] = ttest(..., 'Alpha', alpha, 'Tail', 'both' | 'right' | 'left', 'Dim', dim)
    * h is 1 where the test rejects the hypothesis at the level alpha (0.05 unless given) and 0 where it does not; p is the p-value, ci the confidence interval of the mean (of x - y, for paired data), stats has the t statistic (tstat), its degrees of freedom (df) and the standard deviation (sd).
    * A matrix is tested column by column ('Dim', 2: row by row), NaN values left out. 'right' tests against a mean larger than m, 'left' against a smaller one.
ttest2: The two-sample t-test: do two samples have the same mean?
    h = ttest2(x, y)
    [h, p, ci, stats] = ttest2(x, y, 'Alpha', alpha, 'Tail', tail, 'Vartype', 'equal' | 'unequal')
    * 'unequal' does not take the variances to be equal (Welch's test, with Satterthwaite's degrees of freedom). ci is the interval of mean(x) - mean(y).
ztest: The z-test: is the mean m, for data whose standard deviation sigma is known?
    h = ztest(x, m, sigma)
    [h, p, ci, zval] = ztest(x, m, sigma, 'Alpha', alpha, 'Tail', tail)
vartest: The chi-square test of a variance: is the variance of normal data v?
    h = vartest(x, v)
    [h, p, ci, stats] = vartest(x, v, 'Alpha', alpha, 'Tail', tail)
    * ci is the interval of the variance; stats has the statistic (chisqstat) and its degrees of freedom.
vartest2: The F-test of two variances: do two normal samples have the same variance?
    h = vartest2(x, y)
    [h, p, ci, stats] = vartest2(x, y, 'Alpha', alpha, 'Tail', tail)
    * ci is the interval of var(x)/var(y); stats has fstat, df1 and df2.
vartestn: A test of equal variances in several groups.
    p = vartestn(X)
    p = vartestn(x, group)
    [p, stats] = vartestn(..., 'TestType', type, 'Display', 'off')
    * TestType: 'Bartlett' (the default, for normal data), 'LeveneAbsolute' or 'LeveneQuadratic' (Levene's test on the absolute or squared deviations from the groups' means), 'BrownForsythe' (absolute deviations from the medians) or 'OBrien'. The groups are the columns of X, or the values of x by group. The Command Window shows each group's count, mean and standard deviation unless 'Display' is 'off'.
signtest: The sign test: is the median m (0 unless given), or for paired data the median of x - y zero?
    p = signtest(x)
    p = signtest(x, m)
    p = signtest(x, y)
    [p, h, stats] = signtest(..., 'Alpha', alpha, 'Tail', tail, 'Method', 'exact' | 'approximate')
    * The p-value comes first, then h. Values equal to m count on neither side. The binomial p-value is exact below 100 values, a normal approximation above.
signrank: The Wilcoxon signed rank test: is the median m (0 unless given), or that of x - y zero?
    p = signrank(x)
    p = signrank(x, m)
    p = signrank(x, y)
    [p, h, stats] = signrank(..., 'Alpha', alpha, 'Tail', tail, 'Method', 'exact' | 'approximate')
    * Exact (ties too) up to 15 values; above, a normal approximation corrected for ties, whose z is stats.zval. stats.signedrank is the sum of the ranks of the positive differences.
ranksum: The Wilcoxon rank sum test (Mann-Whitney U): do two samples come from distributions with the same median?
    p = ranksum(x, y)
    [p, h, stats] = ranksum(x, y, 'Alpha', alpha, 'Tail', tail, 'Method', 'exact' | 'approximate')
    * stats.ranksum is the sum of x's ranks among all the values. Exact for small samples (both under 10 and together under 20), a normal approximation corrected for ties above.
kstest: The one-sample Kolmogorov-Smirnov test: do the data come from a given continuous distribution (the standard normal unless given)?
    h = kstest(x)
    [h, p, ksstat, cv] = kstest(x, 'CDF', pd, 'Alpha', alpha, 'Tail', 'unequal' | 'larger' | 'smaller')
    * The distribution is a distribution object (makedist) or a two-column matrix of x and F(x). Its parameters must not be estimated from the same data: for that, lillietest. The p-value is exact.
kstest2: The two-sample Kolmogorov-Smirnov test: do two samples come from the same continuous distribution?
    h = kstest2(x1, x2)
    [h, p, ks2stat] = kstest2(x1, x2, 'Alpha', alpha, 'Tail', 'unequal' | 'larger' | 'smaller')
    * The p-value is the large-sample one, with Stephens' correction for small samples.
lillietest: The Lilliefors test: are the data normal (or exponential, or extreme value), with the parameters estimated from them?
    h = lillietest(x)
    [h, p, kstat, cv] = lillietest(x, 'Alpha', alpha, 'Distr', 'norm' | 'exp' | 'ev')
    * For the normal the p-value is Dallal and Wilkinson's approximation up to 0.1 and Stephens' above. For 'exp' and 'ev' it comes from a simulation of the statistic with a fixed seed, so the same data always give the same p-value.
jbtest: The Jarque-Bera test of normality, from the sample's skewness and kurtosis.
    h = jbtest(x)
    [h, p, jbstat, critval] = jbtest(x, alpha)
    * Up to 2000 values the p-value and the critical value come from a simulation of normal samples of that size (with a fixed seed); above, from the statistic's chi-square limit with 2 degrees of freedom.
adtest: The Anderson-Darling test: do the data come from a family of distributions, or from one distribution?
    h = adtest(x)
    [h, p, adstat, cv] = adtest(x, 'Distribution', 'norm' | 'exp' | 'ev' | 'logn' | 'weibull' | pd, 'Alpha', alpha)
    * With a family's name its parameters are estimated from the data; the p-values of 'norm', 'logn' and 'exp' come from Stephens' formulas, those of 'ev' and 'weibull' from a simulation with a fixed seed. With a distribution object (parameters known) the p-value comes from a simulation too.
chi2gof: The chi-square goodness-of-fit test, on the data counted in bins.
    h = chi2gof(x)
    [h, p, stats] = chi2gof(x, 'CDF', pd, 'NBins', n, 'Edges', edges, 'Ctrs', centers, 'Alpha', alpha)
    [...] = chi2gof(x, 'CDF', @fun)
    [...] = chi2gof(x, 'CDF', {@fun, a, b})
    [...] = chi2gof(x, 'Expected', E, 'NParams', k, 'EMin', 5, 'Frequency', f)
    * Without a distribution the data are tested for normality, with the mean and the standard deviation estimated from them. The parameters in a cell with the function count as estimated, unless NParams says otherwise. 10 bins span the data, the outer ones taking the tails; bins expected to hold fewer than EMin values join their neighbours. A fitted distribution object counts its parameters as estimated. stats has chi2stat, df, the bins' edges, and the observed and expected counts O and E.
runstest: The runs test: do the values above and below a reference (their median unless given) come in random order?
    h = runstest(x)
    h = runstest(x, v)
    [h, p, stats] = runstest(..., 'Alpha', alpha, 'Tail', tail, 'Method', 'exact' | 'approximate')
    * Values equal to the reference are left out. stats has the number of runs (nruns), the counts above (n1) and below (n0), and z. Exact below 50 values.
anova1: One-way analysis of variance: do several groups have the same mean?
    p = anova1(X)
    p = anova1(x, group)
    [p, tbl, stats] = anova1(..., 'off')
    * The groups are the columns of X, or the values of x by group. The Command Window shows the ANOVA table and a figure the groups' box plots, unless the last input is 'off'. tbl is the table as a cell array; stats goes to multcompare.
anova2: Two-way analysis of variance of a balanced layout: the columns are one factor, the rows (in blocks of reps) the other.
    p = anova2(Y)
    p = anova2(Y, reps)
    [p, tbl, stats] = anova2(Y, reps, 'off')
    * With reps > 1 the interaction is tested too. p has the p-values of the columns, the rows and (with reps > 1) the interaction.
kruskalwallis: The Kruskal-Wallis test: do several groups come from distributions with the same median? (One-way analysis of variance of ranks.)
    p = kruskalwallis(X)
    p = kruskalwallis(x, group)
    [p, tbl, stats] = kruskalwallis(..., 'off')
    * The statistic is corrected for ties and its p-value comes from the chi-square distribution. The table and the box plots are shown unless the last input is 'off'.
friedman: Friedman's test: do the columns differ, the rows (blocks) taken out? (Two-way analysis of variance of ranks within blocks.)
    p = friedman(X)
    p = friedman(X, reps)
    [p, tbl, stats] = friedman(X, reps, 'off')
multcompare: Which pairs of groups differ, after anova1, kruskalwallis or friedman.
    c = multcompare(stats)
    [c, m, h, gnames] = multcompare(stats, 'Alpha', alpha, 'CType', type, 'Display', 'off')
    * Each row of c compares two groups: their numbers, the lower end of the interval of the difference, the difference, the upper end, and the p-value. m has each group's mean (or mean rank) and its standard error. CType: 'tukey-kramer' (the default), 'bonferroni', 'dunn-sidak', 'lsd' or 'scheffe'.
    * The figure shows each group's estimate with an interval: two intervals that do not overlap mark a significant difference (exactly so for groups of equal size).
crosstab: A table of counts by two or more grouping variables, with the chi-square test of their independence.
    tbl = crosstab(g1, g2)
    [tbl, chi2, p, labels] = crosstab(g1, g2, ...)
    * tbl(i, j) counts the observations in group i of g1 and group j of g2; labels has the groups' names, a column for each variable.
fishertest: Fisher's exact test of independence in a 2-by-2 table of counts.
    h = fishertest(x)
    [h, p, stats] = fishertest(x, 'Alpha', alpha, 'Tail', tail)
    * stats has the odds ratio and its confidence interval (Woolf's, on the log scale).

# ---- sensitivity analysis and sampling ------------------------------------------------------------
lhsdesign: A Latin hypercube sample in the unit hypercube.
    X = lhsdesign(n, p)
    X = lhsdesign(n, p, 'criterion', c, 'iterations', k)
    X = lhsdesign(n, p, 'smooth', 'off')
    * Each column has one point in each of n equal slices of 0 to 1, the slices in random order. c: 'maximin' (the default: of k samples, 5 unless given, the one whose closest two points are farthest apart), 'correlation' (the one whose columns are least correlated) or 'none'. 'smooth', 'off' puts each point in the middle of its slice.
    * To sample a distribution, map a column through its inverse cdf: norminv(X(:, 1), mu, sigma), icdf(pd, X(:, 2)).
lhsnorm: A Latin hypercube sample of a multivariate normal distribution.
    X = lhsnorm(mu, Sigma, n)
    X = lhsnorm(mu, Sigma, n, 'off')
    [X, Z] = lhsnorm(...)
    * A normal sample Z of mean mu and covariance Sigma whose columns are given one value from each of n slices of equal probability, in the order of their ranks, so that the correlations stay. 'off' takes the middle of each slice.
sobolset: Sobol's low-discrepancy sequence, as a point set.
    p = sobolset(d)
    p = sobolset(d, 'Skip', k, 'Leap', l)
    * Read its points with net(p, n) or p(rows, cols); scramble(p) randomizes it. 'Skip' leaves out the first k points, 'Leap' takes every (l+1)th.
haltonset: Halton's low-discrepancy sequence, as a point set.
    p = haltonset(d)
    p = haltonset(d, 'Skip', k, 'Leap', l)
net: The first points of a point set.
    X = net(p, n)
scramble: A point set scrambled, its points still spread evenly.
    p2 = scramble(p)
    p2 = scramble(p, 'MatousekAffineOwen')
    p2 = scramble(p, 'RR2')
    p2 = scramble(p, 'clear')
src: Standardized regression coefficients: how much the output moves with each input, the others held, in standard deviations.
    S = src(X, Y)
    [S, R2] = src(X, Y)
    * X has a row per run and a column per input, Y the outputs (a column per output for several). S has a row per input. R2 is the regression's R²: below about 0.7 the model is too far from linear for the coefficients to tell much.
srrc: Standardized rank regression coefficients: src of the ranks, for a monotone model that is not linear.
    S = srrc(X, Y)
    [S, R2] = srrc(X, Y)
pcc: Partial correlation coefficients: the correlation of the output with each input, the other inputs' effects removed from both.
    P = pcc(X, Y)
prcc: Partial rank correlation coefficients: pcc of the ranks.
    P = prcc(X, Y)
firstorderindex: A first-order Sobol index of each input, read off any sample by binning.
    S1 = firstorderindex(X, Y)
    S1 = firstorderindex(X, Y, 'Bins', b)
    * The runs sorted by the input and cut into b bins of equal count (the square root of the runs, 4 to 50): the variance of the bins' means over the output's, less what chance gives.
easi: EASI's first-order index of each input, read off any sample.
    S1c = easi(X, Y)
    [S1c, S1] = easi(X, Y, 'Harmonics', h)
    * S1c has the bias a random sample leaves taken off; S1 not.
deltamoment: Borgonovo's moment-independent δ: how far knowing an input moves the output's whole distribution.
    T = deltamoment(X, Y)
    T = deltamoment(X, Y, 'Resamples', r, 'Confidence', c, 'Names', names)
    * A table of δ, the δ adjusted for the bias a bootstrap measures, and the interval around it. Read on the output's normal scores, so a monotone transformation of the output does not change it.
mutualinfo: The mutual information between each input and the output, and how much of it chance would give.
    T = mutualinfo(X, Y)
    T = mutualinfo(X, Y, 'Shuffles', s, 'Confidence', c)
    * A table of MI (in bits, on ranks), Chance (the level Y shuffled gives) and Above (what is above that).
pawn: PAWN: how much the output's distribution changes when an input is held to a slice of its range.
    T = pawn(X, Y)
    T = pawn(X, Y, 'Slides', s)
    * Each input cut into s slices of equal count (10); the Kolmogorov-Smirnov distance between the output's distribution in each slice and overall. A table of the distances' minimum, mean, median (the index usually reported), maximum, spread and coefficient of variation.
discrepancyshares: Each input's share of the discrepancy of the points (input, output).
    S = discrepancyshares(X, Y)
    S = discrepancyshares(X, Y, 'Method', m)
    * m: 'WD' (wrap-around, the default), 'CD', 'MD' or 'L2-star'. An input the output does not depend on spreads the points evenly and has a small share. The cost grows with the square of the runs.
rsa: Regional sensitivity analysis: which inputs separate the runs whose output is high from the rest.
    T = rsa(X, Y)
    T = rsa(X, Y, threshold)
    [T, chance] = rsa(X, Y, threshold, 'Dummies', d)
    * The runs above the threshold (the mean of Y unless given) against the rest; T has each input's Kolmogorov-Smirnov distance between its two distributions and the test's p-value. chance is the distance's mean and standard deviation for d (10) random inputs the output never saw.
morrisdesign: The runs for Morris's elementary effects.
    [X, D] = morrisdesign(K)
    [X, D] = morrisdesign(names)
    [X, D] = morrisdesign(K, 'Trajectories', r, 'Points', m, 'Levels', p)
    [X, D] = morrisdesign(K, 'Design', 'trajectories', 'Candidates', c)
    * X is in the unit hypercube, a row per run: map each column to its input's distribution, run the model, and give the outputs to morrisindices with D. K inputs (or their names).
    * 'Design', 'walks' (the default): r random walks (10) of m runs (10), each step one input one level up or down on a grid of p levels (100). 'trajectories': Morris's own, K + 1 runs each, every input moved once by half the levels; c candidates drawn and the r most spread out kept.
morrisindices: Morris's elementary effects, from the runs of morrisdesign.
    T = morrisindices(D, Y)
    T = morrisindices(D, Y, 'Relative', true, 'Resamples', r)
    * A table of MuStar (the mean of the effects' magnitudes: how much the input matters), MuStarConf (its bootstrap half-width), Mu (the mean effect: which way), Sigma (their spread: a curve or an interaction) and Count. 'Relative' divides each effect by the output.
soboldesign: Saltelli's design for Sobol's indices.
    [X, D] = soboldesign(N, K)
    [X, D] = soboldesign(N, K, 'Second', true, 'Blocks', b, 'Sampling', s)
    * Two samples A and B of N runs and, for each input, A with that input's column from B: (K + 2)N runs; 'Second' adds B with each column from A, (2K + 2)N, for every pair's index. 'Blocks' repeats it for an interval from the spread between blocks. s: 'lhs' (the default), 'random' or 'sobol'.
sobolindices: Sobol's first-order and total indices, from the runs of soboldesign.
    T = sobolindices(D, Y)
    [T, S2, S2conf] = sobolindices(D, Y, 'Estimator', e, 'Resamples', r)
    * S1 is the share of the output's variance an input explains alone, ST the share it has a hand in, interactions included; S1Conf and STConf their half-widths (from blocks, or a bootstrap of one block). S2 is every pair's index, when the design has pairs. e: 'jansen1999' (the default), 'sobol2007', 'homma1996' or 'janon2014'.
efastdesign: The runs of the extended Fourier amplitude sensitivity test.
    [X, D] = efastdesign(N, K)
    [X, D] = efastdesign(N, K, 'Harmonics', m)
    * A curve of N runs per input (raised to the next N at which the harmonics fit), along which that input oscillates fast and the others slowly: KN runs.
efastindices: eFAST's first-order and total indices, from the runs of efastdesign.
    T = efastindices(D, Y)
rbdfastdesign: The runs of the random balance design (RBD-FAST).
    [X, D] = rbdfastdesign(N, K)
    [X, D] = rbdfastdesign(N, K, 'Harmonics', m)
    * N runs along one periodic curve, each input in its own random order: first-order indices for N runs whatever the number of inputs.
rbdfastindices: RBD-FAST's first-order indices, from the runs of rbdfastdesign.
    T = rbdfastindices(D, Y)
    * S1, and S1Corrected with the bias of a random design taken off.
ffdesign: A two-level fractional factorial design of resolution IV.
    [X, D] = ffdesign(K)
    [X, D] = ffdesign(K, 'Low', lo, 'High', hi)
    * Each input at probability lo (0.05) or hi (0.95), as the columns of a Hadamard matrix and its negative say: twice the power of two at or above K runs.
ffindices: Main effects (and interactions) from the runs of ffdesign.
    T = ffindices(D, Y)
    [T, I] = ffindices(D, Y)
    * Main is half the difference between the output's mean with the input high and with it low, Squared its square. I has every pair's interaction effect; in this design each is the sum over the pairs aliased with it.
dgsmdesign: The runs for derivative-based sensitivity measures.
    [X, D] = dgsmdesign(N, K)
    [X, D] = dgsmdesign(N, K, 'Step', h, 'Crossed', true)
    * N points (a Latin hypercube), each moved by h (0.001, in probability) along every input: N(K + 1) runs; 'Crossed' adds every pair.
dgsmindices: Derivative-based measures, from the runs of dgsmdesign.
    T = dgsmindices(D, Y)
    [T, C] = dgsmindices(D, Y, 'Resamples', r)
    * The derivatives are per unit probability. Nu, the mean squared derivative, with NuConf and NuSd; Bound = Nu/(pi^2 Var y), an upper bound on the total Sobol index; Mean and AbsMean; Sigma and Tau. C is every pair's mean squared second derivative.
radialdesign: The radial one-at-a-time design.
    [X, D] = radialdesign(N, K)
    * N base points, each moved one input at a time to a second point's value: N(K + 1) runs.
radialindices: Elementary effects and total indices from the runs of radialdesign.
    T = radialindices(D, Y)
    T = radialindices(D, Y, 'Resamples', r)
    * ST (Jansen's total index) and MuStar, Mu and Sigma of the elementary effects, with bootstrap half-widths STConf and MuStarConf.
shapleydesign: The runs for Shapley effects.
    [X, D] = shapleydesign(K)
    [X, D] = shapleydesign(K, 'Orders', m, 'NVar', nv, 'NOuter', no, 'NInner', ni, 'Correlation', C)
    * nv runs (1000) for the variance, then over m random orders of the inputs (0 for all K!, the default up to 4 inputs; else 100) no points a step (10, or 1 past 4 inputs) with ni draws given each (3). C, a K-by-K correlation matrix, draws the inputs from a Gaussian copula.
shapleyindices: Shapley effects from the runs of shapleydesign.
    T = shapleyindices(D, Y)
    * Each input's fair share of the variance (they add up to one, correlated inputs or not), its standard error and the 95% half-width.

# ---- linear algebra --------------------------------------------------------------------------
inv: The inverse of a square matrix.
    Y = inv(A)
    isys = inv(sys)
    * A \ b is faster and more accurate than inv(A)*b.
    * Of a model: its inverse (square, without delays).
det: The determinant.
    d = det(A)
trace: The sum of the diagonal.
    t = trace(A)
rank: The number of linearly independent rows or columns.
    r = rank(A)
    r = rank(A, tol)
norm: The norm of a vector or a matrix.
    n = norm(v)
    n = norm(v, p)
    n = norm(A)
    n = norm(A, 1 | 2 | Inf | 'fro')
    n = norm(sys)
    n = norm(sys, Inf)
    [n, fpeak] = norm(sys, Inf)
    * Of a model: the H2 norm (Inf with a direct feedthrough in continuous time, or when unstable), or with Inf the H-infinity norm, the peak gain over frequency.
vecnorm: The norm of each column (or along a dimension).
    n = vecnorm(A)
    n = vecnorm(A, p)
    n = vecnorm(A, p, dim)
cond: The condition number (the 2-norm by default).
    c = cond(A)
    c = cond(A, p)
rcond: An estimate of the reciprocal condition number in the 1-norm.
    r = rcond(A)
condest: An estimate of the condition number in the 1-norm.
    c = condest(A)
eig: Eigenvalues and eigenvectors.
    e = eig(A)
    [V, D] = eig(A)
    e = eig(A, B)
    [V, D] = eig(A, B)
eigs: Some eigenvalues (the largest in magnitude by default).
    d = eigs(A)
    d = eigs(A, k)
    d = eigs(A, k, sigma)
    d = eigs(A, B, k, sigma)
    d = eigs(Afun, n, k, sigma)
    d = eigs(..., opts)
    [V, D, flag] = eigs(...)
    * sigma: 'largestabs', 'smallestabs', 'largestreal', 'smallestreal', 'largestimag', 'smallestimag', or a number (the eigenvalues nearest it).
    * Afun(x) gives A*x; with 'smallestabs' or a number it gives (A - sigma*I)\x.
    * opts: a struct or name-value pairs: Tolerance, MaxIterations, SubspaceDimension, StartVector, IsFunctionSymmetric.
svd: The singular value decomposition, A = U*S*V'.
    s = svd(A)
    [U, S, V] = svd(A)
    [U, S, V] = svd(A, 'econ')
svds: Some singular values (the largest by default).
    s = svds(A)
    s = svds(A, k)
    s = svds(A, k, sigma)
    [U, S, V, flag] = svds(...)
    * sigma: 'largest', 'smallest', 'smallestnz' (the smallest that are not zero) or a number (the values nearest it).
qr: The QR decomposition, A = Q*R.
    [Q, R] = qr(A)
    [Q, R] = qr(A, 'econ')
    [Q, R, P] = qr(A)
    [Q, R, p] = qr(A, 'vector')
    [Q, R, p] = qr(A, 0)
    [C, R] = qr(A, B)
    R = qr(A)
    * With three outputs A*P = Q*R; P is a matrix, or a vector of the columns with 'vector' or 0. qr(A, B) gives C = Q'*B, for least squares.
lu: The LU decomposition with row pivoting.
    [L, U] = lu(A)
    [L, U, P] = lu(A)
    [L, U, P] = lu(A, 'vector')
    [L, U, P, Q] = lu(S)
    * For a sparse S the factors are sparse; with four outputs the columns are also ordered to keep them sparse: P*S*Q = L*U.
chol: The Cholesky factor of a symmetric positive definite matrix, A = R'*R.
    R = chol(A)
    L = chol(A, 'lower')
    [R, p] = chol(A)
schur: The Schur decomposition, A = U*T*U'.
    T = schur(A)
    [U, T] = schur(A)
    [U, T] = schur(A, 'complex')
hess: The Hessenberg form, A = P*H*P'.
    H = hess(A)
    [P, H] = hess(A)
pinv: The Moore-Penrose pseudoinverse.
    B = pinv(A)
    B = pinv(A, tol)
null: An orthonormal basis of the null space.
    Z = null(A)
orth: An orthonormal basis of the range.
    Q = orth(A)
rref: The reduced row echelon form.
    R = rref(A)
    [R, p] = rref(A)
expm: The matrix exponential.
    Y = expm(A)
logm: The matrix logarithm.
    L = logm(A)
sqrtm: The principal matrix square root.
    X = sqrtm(A)
funm: A function of a matrix, given as a handle of an elementwise function.
    F = funm(A, @fun)
cross: The cross product of 3-element vectors.
    C = cross(a, b)
    C = cross(A, B, dim)
dot: The dot product.
    d = dot(a, b)
    d = dot(A, B, dim)
linsolve: Solve A*x = b, optionally saying what kind of matrix A is.
    x = linsolve(A, b)
    x = linsolve(A, b, opts)
balance: Balance a matrix to make its eigenvalues more accurate.
    B = balance(A)
    [T, B] = balance(A)
givens: The 2-by-2 rotation G with G*[x; y] = [r; 0].
    G = givens(x, y)
planerot: A Givens rotation and the rotated vector.
    [G, y] = planerot(x)
isdiag: True when every element off the diagonal is zero.
    tf = isdiag(A)

# ---- sparse matrices -------------------------------------------------------------------------
sparse: A sparse matrix from triplets, or a matrix made sparse.
    S = sparse(A)
    S = sparse(i, j, v)
    S = sparse(i, j, v, m, n)
    S = sparse(i, j, v, m, n, nz)
    S = sparse(m, n)
    * Only the nonzero elements are stored, with their places. Values given for one place are added (logical ones combined by or).
    * Sparse matrices are double or logical, and two-dimensional.
    * Results stay sparse where the language keeps them sparse: S + S, S - S, S .* A, S * S, S \ S, S', comparisons and logical operators, indexing, concatenation with a sparse part, and functions that keep zeros zero (abs, sqrt, sin, round, sum, max, cumsum, diag, kron, ...). S + A, S * A and S \ b with A and b full are full, and so is S + 1.
    * zeros, ones and eye with 'like' and a sparse value are sparse; so are true and false 'like' a sparse logical.
full: A sparse matrix as a full one.
    A = full(S)
issparse: True for a sparse matrix.
    tf = issparse(S)
nzmax: The room for nonzero elements: the number of them (at least 1).
    n = nzmax(S)
spalloc: An all-zero matrix with room for nonzeros.
    S = spalloc(m, n, nz)
speye: The identity matrix, sparse.
    S = speye(n)
    S = speye(m, n)
spones: Ones where a matrix has nonzeros.
    R = spones(S)
sprand: A random matrix with a given density of nonzeros (uniform).
    R = sprand(m, n, density)
sprandn: A random matrix with a given density of nonzeros (normal).
    R = sprandn(m, n, density)
spzeros: An all-zero matrix.
    S = spzeros(m, n)
spdiags: A matrix built from diagonals, or the diagonals taken from one.
    S = spdiags(B, d, m, n)
    A = spdiags(B, d, A)
    [B, d] = spdiags(A)
    B = spdiags(A, d)
spconvert: A sparse matrix from rows [i j v] or [i j re im].
    S = spconvert(D)
    * A last row [m n 0] sets the size.
sprandsym: A random symmetric sparse matrix of normal values.
    R = sprandsym(n, density)
    R = sprandsym(S)
normest: An estimate of the 2-norm, by the power method.
    n = normest(S)
    n = normest(S, tol)
    [n, count] = normest(...)
symrcm: The reverse Cuthill-McKee ordering, which brings the nonzeros near the diagonal.
    p = symrcm(S)
amd: A fill-reducing ordering of a symmetric matrix (minimum degree).
    p = amd(S)
symamd: A fill-reducing ordering of a symmetric matrix (minimum degree).
    p = symamd(S)
colamd: A column ordering for a sparse LU or QR factorization (minimum degree on S'*S).
    p = colamd(S)
etree: The elimination tree of a symmetric matrix.
    p = etree(A)
    [p, q] = etree(A)
    * p(j) is the parent of column j (0 for a root); q orders the tree so that each column comes after its children.
dmperm: A maximum matching of the columns to the rows.
    p = dmperm(A)
    * p(j) is the row matched to column j, 0 for none. Only this first output is given.
sprank: The structural rank: the size of a maximum matching.
    r = sprank(A)
ichol: The incomplete Cholesky factor, L*L' close to A.
    L = ichol(A)
    L = ichol(A, opts)
    * A is read from its lower triangle (its upper one with opts.shape 'upper', which gives L'). A pivot that is not real and positive is an error.
    * opts.type: 'nofill' (the default) keeps A's pattern; 'ict' drops entries smaller than opts.droptol times the 1-norm of the column of A below the diagonal.
    * opts.michol 'on' adds what is dropped to the diagonal, so that L*L' has A's row sums; opts.diagcomp alpha factors A + alpha*diag(diag(A)).
ilu: Incomplete LU factors of a sparse matrix, L*U close to A.
    W = ilu(A)
    [L, U] = ilu(A, opts)
    [L, U, P] = ilu(A, opts)
    * opts.type: 'nofill' (the default) keeps A's pattern; 'crout' drops entries smaller than opts.droptol times norm(A(:, j)); 'ilutp' drops them too and pivots, choosing another row when the diagonal one is smaller than opts.thresh (1) times the largest. P*A = L*U then; with two outputs L carries P's rows.
    * opts.milu 'row' or 'col' adds what is dropped to the diagonal of U, so that L*U has A's row or column sums; opts.udiag 1 replaces a zero on U's diagonal by the drop tolerance.
    * W = ilu(A) is L + U - I.
spaugment: The augmented matrix [c*I A; A' 0] of a least-squares problem.
    S = spaugment(A)
    S = spaugment(A, c)
spparms: The sparse solvers' settings.
    spparms
    v = spparms(key)
    [keys, values] = spparms
    spparms(key, value)
    spparms(values)
    spparms('default')
    * The settings are kept and read back, but change nothing: the solvers keep their own. 'tight' is accepted and changes nothing.
spy: A dot at each nonzero element.
    spy(S)
    spy(S, markersize)
    spy(S, linespec, markersize)

# ---- special functions -----------------------------------------------------------------------
gamma: The gamma function; gamma(n+1) = n!.
    y = gamma(x)
gammaln: The logarithm of the gamma function, without overflow.
    y = gammaln(x)
gammainc: The regularized incomplete gamma function.
    y = gammainc(x, a)
    y = gammainc(x, a, 'upper')
    y = gammainc(x, a, 'scaledlower')
    y = gammainc(x, a, 'scaledupper')
    * The scaled forms are multiplied by gamma(a+1)*exp(x)/x^a.
gammaincinv: The inverse of the regularized incomplete gamma function.
    x = gammaincinv(y, a)
    x = gammaincinv(y, a, 'upper')
beta: The beta function.
    y = beta(z, w)
betaln: The logarithm of the beta function.
    y = betaln(z, w)
betainc: The regularized incomplete beta function.
    y = betainc(x, z, w)
    y = betainc(x, z, w, 'upper')
betaincinv: The inverse of the regularized incomplete beta function.
    x = betaincinv(y, z, w)
erf: The error function.
    y = erf(x)
erfc: The complementary error function, 1 - erf(x), accurate in the tail.
    y = erfc(x)
erfinv: The inverse error function.
    x = erfinv(y)
erfcinv: The inverse complementary error function.
    x = erfcinv(y)
erfcx: The scaled complementary error function, exp(x.^2).*erfc(x).
    y = erfcx(x)
expint: The exponential integral E1(x).
    y = expint(x)
psi: The digamma function, or its derivatives.
    y = psi(x)
    y = psi(k, x)
besselj: The Bessel function of the first kind.
    J = besselj(nu, z)
    J = besselj(nu, z, 1)
bessely: The Bessel function of the second kind.
    Y = bessely(nu, z)
besseli: The modified Bessel function of the first kind.
    I = besseli(nu, z)
    I = besseli(nu, z, 1)
besselk: The modified Bessel function of the second kind.
    K = besselk(nu, z)
    K = besselk(nu, z, 1)
besselh: The Bessel function of the third kind (Hankel function).
    H = besselh(nu, z)
    H = besselh(nu, k, z)
airy: The Airy functions Ai, Ai', Bi and Bi'.
    W = airy(z)
    W = airy(k, z)
    W = airy(k, z, 1)
    * k is 0 for Ai, 1 for Ai', 2 for Bi, 3 for Bi'. With 1 as the third input, Ai and Ai' are scaled by exp(2/3*z^(3/2)), Bi and Bi' by exp(-abs(real(2/3*z^(3/2)))).
ellipke: Complete elliptic integrals of the first and second kind.
    K = ellipke(m)
    [K, E] = ellipke(m)
ellipj: Jacobi elliptic functions.
    [sn, cn, dn] = ellipj(u, m)
legendre: Associated Legendre functions of degree n.
    P = legendre(n, x)
    P = legendre(n, x, 'norm' | 'sch')

# ---- polynomials, filters and transforms ------------------------------------------------------
polyfit: Fit a polynomial by least squares; coefficients from the highest power down.
    p = polyfit(x, y, n)
    [p, S] = polyfit(x, y, n)
    [p, S, mu] = polyfit(x, y, n)
polyval: Evaluate a polynomial.
    y = polyval(p, x)
    y = polyval(p, x, [], mu)
    [y, delta] = polyval(p, x, S)
    [y, delta] = polyval(p, x, S, mu)
    * delta, from the structure S of polyfit, is the standard error of each prediction.
polyvalm: Evaluate a polynomial of a matrix.
    Y = polyvalm(p, X)
roots: The roots of a polynomial.
    r = roots(p)
poly: The polynomial with given roots, or the characteristic polynomial of a matrix.
    p = poly(r)
    p = poly(A)
conv: Convolution, or polynomial multiplication.
    w = conv(u, v)
    w = conv(u, v, 'same' | 'valid')
deconv: Deconvolution, or polynomial division.
    [q, r] = deconv(u, v)
polyder: The derivative of a polynomial (of a product or quotient, with two).
    k = polyder(p)
    k = polyder(a, b)
    [q, d] = polyder(a, b)
polyint: The integral of a polynomial.
    q = polyint(p)
    q = polyint(p, k)
residue: Partial fractions of a ratio of polynomials, and back.
    [r, p, k] = residue(b, a)
    [b, a] = residue(r, p, k)
filter: A rational transfer function (IIR or FIR filter) applied to data.
    y = filter(b, a, x)
    [y, zf] = filter(b, a, x, zi)
    y = filter(b, a, x, zi, dim)
filter2: A 2-D FIR filter.
    Y = filter2(h, X)
    Y = filter2(h, X, shape)
conv2: 2-D convolution.
    C = conv2(A, B)
    C = conv2(A, B, 'same' | 'valid')
    C = conv2(u, v, A)
convn: Convolution in any number of dimensions.
    C = convn(A, B)
    C = convn(A, B, shape)
fft: The discrete Fourier transform.
    Y = fft(X)
    Y = fft(X, n)
    Y = fft(X, n, dim)
ifft: The inverse discrete Fourier transform.
    X = ifft(Y)
    X = ifft(Y, n)
    X = ifft(..., 'symmetric')
fft2: The 2-D discrete Fourier transform.
    Y = fft2(X)
    Y = fft2(X, m, n)
ifft2: The inverse 2-D discrete Fourier transform.
    X = ifft2(Y)
fftn: The discrete Fourier transform in every dimension.
    Y = fftn(X)
ifftn: The inverse of fftn.
    X = ifftn(Y)
fftshift: Move the zero frequency to the middle of the spectrum.
    Y = fftshift(X)
    Y = fftshift(X, dim)
ifftshift: Undo fftshift.
    X = ifftshift(Y)
detrend: Remove a linear trend (or a constant, or a polynomial).
    y = detrend(x)
    y = detrend(x, n)
    y = detrend(x, 'constant')
gradient: Numerical gradient by central differences.
    g = gradient(f)
    g = gradient(f, h)
    [gx, gy] = gradient(F)
    [gx, gy] = gradient(F, hx, hy)
    [gx, gy, gz, ...] = gradient(F, hx, hy, hz, ...)
    * x is the second dimension, y the first, then the third and on. A spacing is a scalar or the coordinates; inside the differences are (f(i+1) - f(i-1))/(x(i+1) - x(i-1)), at the ends one-sided.
del2: The discrete Laplacian, divided by 2N in N dimensions (by 4 for a vector).
    L = del2(U)
    L = del2(U, h)
    L = del2(U, hx, hy, ...)
    * At the edges the second differences are extended linearly from the inner points. Spacings as for gradient.

# ---- interpolation ---------------------------------------------------------------------------
interp1: Interpolation in one dimension.
    vq = interp1(x, v, xq)
    vq = interp1(x, v, xq, method)
    vq = interp1(x, v, xq, method, 'extrap')
    vq = interp1(x, v, xq, method, extrapval)
    pp = interp1(x, v, method, 'pp')
    vq = interp1(v, xq, method, extrapval)
    * method is 'linear' (the default), 'nearest', 'next', 'previous', 'pchip', 'cubic', 'makima' or 'spline'.
interp2: Interpolation on a 2-D grid.
    Vq = interp2(X, Y, V, Xq, Yq)
    Vq = interp2(V, Xq, Yq)
    Vq = interp2(V)
    Vq = interp2(V, k)
    Vq = interp2(..., method)
    Vq = interp2(..., method, extrapval)
    * method is 'linear', 'nearest' (a half rounds up), 'cubic' (cubic convolution on even grids), 'spline', 'makima' or 'pchip'. A row Xq and a column Yq make a grid. interp2(V, k) refines the grid k times (once unless given). Outside the grid the values are NaN unless extrapval is given.
interpn: Interpolation on a grid in any number of dimensions.
    Vq = interpn(X1, X2, ..., V, Xq1, Xq2, ...)
    Vq = interpn(V, Xq1, Xq2, ...)
    Vq = interpn(V, k)
    Vq = interpn(..., method, extrapval)
    * Query vectors of different sizes make a grid, as ndgrid does.
griddata: Interpolate scattered points onto a grid.
    vq = griddata(x, y, v, xq, yq)
    vq = griddata(x, y, v, xq, yq, method)
spline: A cubic spline (not-a-knot ends, or clamped when two more values are given).
    yq = spline(x, y, xq)
    pp = spline(x, y)
pchip: Piecewise cubic Hermite interpolation that keeps the data's shape (no overshoot).
    yq = pchip(x, y, xq)
    pp = pchip(x, y)
makima: Modified Akima piecewise cubic interpolation.
    yq = makima(x, y, xq)
    pp = makima(x, y)
ppval: Evaluate a piecewise polynomial.
    v = ppval(pp, xq)
mkpp: Make a piecewise polynomial from its breaks and coefficients.
    pp = mkpp(breaks, coefs)
unmkpp: The breaks and coefficients of a piecewise polynomial.
    [breaks, coefs, l, k, d] = unmkpp(pp)

# ---- apps ----------------------------------------------------------------------------------------------------------------
uifigure: A window for an app: no number, its handle hidden, no menus or tools.
    fig = uifigure
    fig = uifigure(Name, Value, ...)
    * Its Position is in pixels ([100 100 640 480] unless given). Components, panels, grid layouts and uiaxes go in it; plotting needs the axes given (plot(ax, ...)), as a uifigure is never the current figure.
uibutton: A push button, or a state button that stays pressed.
    b = uibutton(parent)
    b = uibutton(parent, 'state')
    b = uibutton(..., Name, Value)
    * Text, Icon and IconAlignment; ButtonPushedFcn runs when it is pushed, ValueChangedFcn when a state button changes (Value true or false).
uilabel: Text in an app.
    l = uilabel(parent, 'Text', 'Name:')
    * HorizontalAlignment, VerticalAlignment, WordWrap, FontSize, FontWeight, FontColor and BackgroundColor.
uieditfield: A field for text, or for a number.
    e = uieditfield(parent)
    e = uieditfield(parent, 'numeric')
    e = uieditfield(..., Name, Value)
    * A numeric field keeps its Value within Limits (a number typed outside them is not taken), shows it by ValueDisplayFormat, and RoundFractionalValues rounds it. ValueChangedFcn runs when the typing is done (Enter or leaving the field), ValueChangingFcn as a text field is typed in.
uitextarea: A field of several lines.
    t = uitextarea(parent, 'Value', {'line 1'; 'line 2'})
    * Value is a column cell of the lines.
uidropdown: A list that opens to choose one item (or, Editable, to type one).
    d = uidropdown(parent, 'Items', {'a', 'b', 'c'})
    d = uidropdown(..., 'ItemsData', [1 2 3])
    * Value is the chosen item, or its element of ItemsData when that is set.
uilistbox: A list to choose one item, or several with Multiselect.
    l = uilistbox(parent, 'Items', {'a', 'b', 'c'})
    l = uilistbox(..., 'Multiselect', 'on')
uicheckbox: A check box.
    c = uicheckbox(parent, 'Text', 'Show grid')
    * Value is true or false.
uiswitch: A switch between two items: slider, rocker or toggle.
    s = uiswitch(parent)
    s = uiswitch(parent, 'rocker')
    s = uiswitch(parent, 'toggle')
    * Items (Off and On unless given); Value is one of them.
uislider: A slider with its ticks and their labels.
    s = uislider(parent, 'Limits', [0 10])
    * MajorTicks, MajorTickLabels, Orientation; ValueChangingFcn runs as it is dragged (event.Value), ValueChangedFcn when it is let go.
uispinner: A number field with arrows that step it.
    s = uispinner(parent, 'Step', 0.5, 'Limits', [0 10])
uiknob: A knob turned with the mouse: continuous over Limits, or discrete among Items.
    k = uiknob(parent)
    k = uiknob(parent, 'discrete')
uigauge: A gauge showing a value: circular, linear, ninety-degree or semicircular.
    g = uigauge(parent)
    g = uigauge(parent, 'linear')
    * ScaleColors with ScaleColorLimits colour parts of its scale ({'green', 'red'} with [0 60; 60 100]).
uilamp: A lamp of a colour.
    l = uilamp(parent, 'Color', [1 0 0])
uiradiobutton: A radio button in a button group; choosing it clears the group's others.
    r = uiradiobutton(bg, 'Text', 'Fast')
    * The group's SelectionChangedFcn runs when the choice changes, with OldValue and NewValue.
uitogglebutton: A toggle button in a button group; pressing it releases the group's others.
    t = uitogglebutton(bg, 'Text', 'A')
uiimage: A picture in an app, from a file or an RGB array.
    im = uiimage(parent, 'ImageSource', 'logo.png')
    * ScaleMethod fit, fill, none, scaledown or stretch; ImageClickedFcn runs when it is clicked.
uihyperlink: A link in an app; clicking it opens the URL.
    h = uihyperlink(parent, 'Text', 'Help', 'URL', 'https://...')
uigridlayout: Rows and columns that place the components put in them, filling the parent.
    g = uigridlayout(parent)
    g = uigridlayout(parent, [rows cols])
    * RowHeight and ColumnWidth: pixels, 'fit', or weights such as '1x' and '2x' that share what is left; Padding [left bottom right top], RowSpacing and ColumnSpacing. A child's Layout.Row and Layout.Column (a number, or [first last] to span) say where it goes; without them, the next free cell in order.
uiaxes: Axes in an app.
    ax = uiaxes(parent)
    * Plot into them by giving them: plot(ax, x, y), title(ax, '...').
uialert: A message in an app's window.
    uialert(fig, message, title)
    uialert(fig, message, title, 'Icon', 'warning')
uiconfirm: A question in an app's window; the chosen option is returned.
    choice = uiconfirm(fig, message, title)
    choice = uiconfirm(fig, message, title, 'Options', {'Save', 'Discard', 'Cancel'})
uiprogressdlg: A progress bar for a long task.
    d = uiprogressdlg(fig, 'Title', 'Working', 'Message', 'Reading files')
    * d.Value (0 to 1) and d.Message move it on; close(d) removes it.
createCallbackFcn: What an app's class gives its components as callbacks: its method, called with the app (and the event data).
    comp.ButtonPushedFcn = createCallbackFcn(app, @MethodName, true)
registerApp: Ties an app to its window, so that closing the window deletes the app.
    registerApp(app, app.UIFigure)
runStartupFcn: Runs an app's startup method with the app.
    runStartupFcn(app, @startupFcn)
appdesigner: The app designer: lay out an app's window with the mouse and write its class.
    appdesigner
    appdesigner('MyApp')
    * Components are added from the palette (click, or drag onto the window), moved and resized with the mouse or the arrow keys, and set in the inspector, with a callback's name and code. Save writes MyApp.m in the current folder, a class as App Designer writes them (with the layout in a comment at its end, so the designer opens it again); Run saves and runs it; Code opens the file in the Editor, where the callbacks may be written as well.
    * Back to the layout from the code: Design App on the EDITOR tab (with the app's file open there), Open in App Designer on the file in the Current Folder, or appdesigner('MyApp'). The designer takes the callbacks as the Editor has them, saved or not; the rest of the class it writes again, so changes made elsewhere in it are not kept.

# ---- mapping ------------------------------------------------------------------------------------------------------
deg2km: Degrees of arc on a sphere as kilometers (the Earth's mean radius 6371 km unless given).
    km = deg2km(deg)
    km = deg2km(deg, radius)
    km = deg2km(deg, 'moon')
km2deg: Kilometers as degrees of arc on a sphere.
    deg = km2deg(km)
    deg = km2deg(km, radius)
deg2nm: Degrees of arc as nautical miles.
    nm = deg2nm(deg)
nm2deg: Nautical miles as degrees of arc.
    deg = nm2deg(nm)
deg2sm: Degrees of arc as statute miles.
    sm = deg2sm(deg)
sm2deg: Statute miles as degrees of arc.
    deg = sm2deg(sm)
km2nm: Kilometers as nautical miles (1852 m).
    nm = km2nm(km)
nm2km: Nautical miles as kilometers.
    km = nm2km(nm)
km2sm: Kilometers as statute miles (1609.344 m).
    sm = km2sm(km)
sm2km: Statute miles as kilometers.
    km = sm2km(sm)
nm2sm: Nautical miles as statute miles.
    sm = nm2sm(nm)
sm2nm: Statute miles as nautical miles.
    nm = sm2nm(sm)
km2rad: Kilometers as radians of arc on a sphere.
    rad = km2rad(km)
    rad = km2rad(km, radius)
rad2km: Radians of arc as kilometers on a sphere.
    km = rad2km(rad)
    km = rad2km(rad, radius)
unitsratio: The factor from one unit of length (or angle) to another.
    r = unitsratio(to, from)
    * Units: meter, kilometer, centimeter, millimeter, nauticalmile, foot, surveyfoot, mile, yard, inch; degree and radian.
dms2degrees: Degrees, minutes and seconds (rows of three) as degrees.
    deg = dms2degrees([d m s])
degrees2dms: Degrees as rows of degrees, minutes and seconds; the sign on the first part that is not zero.
    dms = degrees2dms(deg)
dm2degrees: Degrees and minutes (rows of two) as degrees.
    deg = dm2degrees([d m])
degrees2dm: Degrees as rows of degrees and minutes.
    dm = degrees2dm(deg)
wrapTo180: Angles in degrees wrapped to [-180, 180].
    lon = wrapTo180(lon)
wrapTo360: Angles in degrees wrapped to [0, 360] (a positive multiple of 360 stays 360).
    lon = wrapTo360(lon)
wrapToPi: Angles in radians wrapped to [-pi, pi].
    a = wrapToPi(a)
wrapTo2Pi: Angles in radians wrapped to [0, 2*pi].
    a = wrapTo2Pi(a)
referenceEllipsoid: A reference ellipsoid by name or EPSG code, in a unit of length.
    E = referenceEllipsoid('wgs84')
    E = referenceEllipsoid('grs80', 'kilometer')
    E = referenceEllipsoid(7030)
    * Names: wgs84, grs80, wgs72, grs67, international (Hayford 1924), clarke66, clarke80, bessel, airy1830, krasovsky, everest. Its properties: SemimajorAxis, SemiminorAxis, InverseFlattening, Eccentricity, Flattening, ThirdFlattening, MeanRadius, SurfaceArea, Volume, LengthUnit (settable), Name and Code.
wgs84Ellipsoid: The WGS 84 ellipsoid.
    E = wgs84Ellipsoid
    E = wgs84Ellipsoid('kilometer')
referenceSphere: A sphere of a body's mean radius.
    S = referenceSphere('earth')
    S = referenceSphere('moon', 'kilometer')
    * Bodies: earth (6371 km), sun, moon, mercury, venus, mars, jupiter, saturn, uranus, neptune, pluto, 'unit sphere'.
earthRadius: The Earth's mean radius, 6371 km, in a unit of length.
    r = earthRadius
    r = earthRadius('kilometer')
distance: The distance and azimuth between points along a great circle or a rhumb line.
    d = distance(lat1, lon1, lat2, lon2)
    d = distance(pt1, pt2)
    [d, az] = distance(lat1, lon1, lat2, lon2, ellipsoid)
    d = distance('rh', lat1, lon1, lat2, lon2)
    d = distance(..., 'radians')
    * Without an ellipsoid the distance is in degrees of arc on a sphere; with one, the geodesic length in its units. Azimuths are clockwise from north.
azimuth: The azimuth from one point to another, clockwise from north.
    az = azimuth(lat1, lon1, lat2, lon2)
    az = azimuth(lat1, lon1, lat2, lon2, ellipsoid)
    az = azimuth('rh', ...)
reckon: The point at a distance and azimuth from another.
    [lat2, lon2] = reckon(lat, lon, arclen, az)
    [lat2, lon2] = reckon(lat, lon, arclen, az, ellipsoid)
    [lat2, lon2] = reckon('rh', ...)
    * arclen is in degrees of arc without an ellipsoid, in its units with one.
track2: Points along the great circle (or geodesic, or rhumb line) between two points.
    [lat, lon] = track2(lat1, lon1, lat2, lon2)
    [lat, lon] = track2(lat1, lon1, lat2, lon2, ellipsoid, units, npts)
    [lat, lon] = track2('rh', ...)
track1: Points along a great circle (or rhumb line) from a point in a direction.
    [lat, lon] = track1(lat, lon, az)
    [lat, lon] = track1(lat, lon, az, arclen)
    [lat, lon] = track1(lat, lon, az, arclen, ellipsoid, units, npts)
gcwaypts: Waypoints along a great circle, for rhumb-line legs that follow it.
    [lat, lon] = gcwaypts(lat1, lon1, lat2, lon2)
    [lat, lon] = gcwaypts(lat1, lon1, lat2, lon2, nlegs)
meridianarc: The distance along a meridian between two latitudes (in radians) on an ellipsoid.
    s = meridianarc(phi1, phi2, ellipsoid)
antipode: The point on the other side of the globe.
    [lat2, lon2] = antipode(lat, lon)
areaint: The area of polygons on the sphere, as a fraction of its surface, or with an ellipsoid in its units squared.
    a = areaint(lat, lon)
    a = areaint(lat, lon, ellipsoid)
    * The edges are great circles; parts are separated by NaN.
areaquad: The area of a quadrangle between two parallels and two meridians.
    a = areaquad(lat1, lon1, lat2, lon2)
    a = areaquad(lat1, lon1, lat2, lon2, ellipsoid)
interpm: More points along a line in latitude and longitude, no two farther apart than a step.
    [lat, lon] = interpm(lat, lon, maxdiff)
    [lat, lon] = interpm(lat, lon, maxdiff, 'gc')
geodetic2ecef: Geodetic coordinates as Earth-centred, Earth-fixed x, y and z.
    [x, y, z] = geodetic2ecef(spheroid, lat, lon, h)
    [x, y, z] = geodetic2ecef(spheroid, lat, lon, h, 'radians')
    * WGS 84 in meters unless a spheroid is given.
ecef2geodetic: Earth-centred, Earth-fixed coordinates as latitude, longitude and height.
    [lat, lon, h] = ecef2geodetic(spheroid, x, y, z)
geodetic2enu: A point as east, north and up from a local origin.
    [xEast, yNorth, zUp] = geodetic2enu(lat, lon, h, lat0, lon0, h0, spheroid)
enu2geodetic: East, north and up from a local origin as latitude, longitude and height.
    [lat, lon, h] = enu2geodetic(xEast, yNorth, zUp, lat0, lon0, h0, spheroid)
geodetic2ned: A point as north, east and down from a local origin.
    [xNorth, yEast, zDown] = geodetic2ned(lat, lon, h, lat0, lon0, h0, spheroid)
ned2geodetic: North, east and down from a local origin as latitude, longitude and height.
    [lat, lon, h] = ned2geodetic(xNorth, yEast, zDown, lat0, lon0, h0, spheroid)
geodetic2aer: A point as azimuth, elevation and slant range from a local origin.
    [az, elev, slantRange] = geodetic2aer(lat, lon, h, lat0, lon0, h0, spheroid)
aer2geodetic: Azimuth, elevation and slant range from a local origin as latitude, longitude and height.
    [lat, lon, h] = aer2geodetic(az, elev, slantRange, lat0, lon0, h0, spheroid)
ecef2enu: Earth-centred, Earth-fixed coordinates as east, north and up from a local origin.
    [xEast, yNorth, zUp] = ecef2enu(x, y, z, lat0, lon0, h0, spheroid)
enu2ecef: East, north and up from a local origin as Earth-centred, Earth-fixed coordinates.
    [x, y, z] = enu2ecef(xEast, yNorth, zUp, lat0, lon0, h0, spheroid)
ecef2ned: Earth-centred, Earth-fixed coordinates as north, east and down from a local origin.
    [xNorth, yEast, zDown] = ecef2ned(x, y, z, lat0, lon0, h0, spheroid)
ned2ecef: North, east and down from a local origin as Earth-centred, Earth-fixed coordinates.
    [x, y, z] = ned2ecef(xNorth, yEast, zDown, lat0, lon0, h0, spheroid)
ecef2aer: Earth-centred, Earth-fixed coordinates as azimuth, elevation and slant range from a local origin.
    [az, elev, slantRange] = ecef2aer(x, y, z, lat0, lon0, h0, spheroid)
aer2ecef: Azimuth, elevation and slant range from a local origin as Earth-centred, Earth-fixed coordinates.
    [x, y, z] = aer2ecef(az, elev, slantRange, lat0, lon0, h0, spheroid)
enu2aer: East, north and up as azimuth, elevation and slant range.
    [az, elev, slantRange] = enu2aer(xEast, yNorth, zUp)
aer2enu: Azimuth, elevation and slant range as east, north and up.
    [xEast, yNorth, zUp] = aer2enu(az, elev, slantRange)
ned2aer: North, east and down as azimuth, elevation and slant range.
    [az, elev, slantRange] = ned2aer(xNorth, yEast, zDown)
aer2ned: Azimuth, elevation and slant range as north, east and down.
    [xNorth, yEast, zDown] = aer2ned(az, elev, slantRange)
inpolygon: Which points lie inside a polygon (or on its edge).
    in = inpolygon(xq, yq, xv, yv)
    [in, on] = inpolygon(xq, yq, xv, yv)
    * NaN separates the parts of the polygon; a part inside another is a hole.
polyarea: The area of a polygon in the plane.
    a = polyarea(x, y)
ispolycw: Whether the parts of a polygon run clockwise.
    tf = ispolycw(x, y)
poly2cw: A polygon's parts made to run clockwise.
    [x, y] = poly2cw(x, y)
poly2ccw: A polygon's parts made to run counterclockwise.
    [x, y] = poly2ccw(x, y)
polysplit: The NaN-separated parts of a polygon or line as cells.
    [xc, yc] = polysplit(x, y)
polyjoin: Cells of parts joined into one NaN-separated polygon or line.
    [x, y] = polyjoin(xc, yc)
polyxpoly: Where two polylines cross.
    [xi, yi] = polyxpoly(x1, y1, x2, y2)
    [xi, yi, ii] = polyxpoly(x1, y1, x2, y2)
projcrs: A projected coordinate reference system by its EPSG code.
    p = projcrs(3006)
    p = projcrs(32633)
    * Known without PROJ: WGS 84 UTM zones (326xx north, 327xx south), ETRS89 UTM (258xx), SWEREF99 TM (3006) and its local zones (3007 to 3018), RT90 2.5 gon V (3021), Pseudo-Mercator (3857), World Mercator (3395), LAEA Europe (3035), LCC Europe (3034), Lambert-93 (2154), British National Grid (27700), Conus Albers (5070) and UPS (32661, 32761). Other codes are looked up with PROJ (pyproj) when it is there.
geocrs: A geographic coordinate reference system by its EPSG code.
    g = geocrs(4326)
projfwd: Latitude and longitude as projected x and y.
    [x, y] = projfwd(proj, lat, lon)
    * proj is a projcrs object or a map projection structure (gcm, defaultm).
projinv: Projected x and y as latitude and longitude.
    [lat, lon] = projinv(proj, x, y)
axesm: Make map axes with a projection.
    axesm(projection)
    axesm(projection, Name, Value, ...)
    axesm('MapProjection', name, Name, Value, ...)
    * Projections: eqdcylin, pcarree, miller, eqacylin, mercator, tranmerc, utm, lambert, lambertstd, eqaconic, eqaconicstd, eqdconic, eqdconicstd, ortho, stereo, gnomonic, eqdazim, eqaazim, ups, sinusoid, mollweid, hammer, robinson, equalearth. Properties: MapLatLimit, MapLonLimit, Origin, MapParallels, Zone, Geoid, FalseEasting, FalseNorthing, ScaleFactor, Frame, Grid, MeridianLabel, ParallelLabel, MLineLocation, PLineLocation, MLabelLocation, PLabelLocation, MLabelParallel, PLabelMeridian, GColor, GLineStyle, GLineWidth, FEdgeColor, FFaceColor, FLineWidth, FontSize. Positions are in units of the Geoid (a unit sphere unless given).
worldmap: Map axes for a region of the world, the projection chosen to suit it.
    worldmap('World')
    worldmap(region)
    worldmap(latlim, lonlim)
    * Regions: World, Europe, Africa, Asia, North America, South America, Australia, Antarctica, Arctic, Sweden, Scandinavia, Nordic. The frame, graticule and labels are on.
setm: Change the properties of map axes.
    setm(ax, Name, Value, ...)
getm: A property of map axes.
    v = getm(ax, name)
gcm: The current map axes' projection and look, as a structure.
    mstruct = gcm
    mstruct = gcm(ax)
defaultm: A map projection structure with its defaults.
    mstruct = defaultm(projection)
ismap: Whether axes are map axes.
    tf = ismap
    tf = ismap(ax)
framem: Show or hide the map frame.
    framem
    framem('on' | 'off')
    framem(Name, Value, ...)
gridm: Show or hide the map graticule.
    gridm
    gridm('on' | 'off')
    gridm(Name, Value, ...)
mlabel: Show or hide the meridian labels.
    mlabel('on' | 'off')
plabel: Show or hide the parallel labels.
    plabel('on' | 'off')
tightmap: Map axes' limits fitted tightly to the frame.
    tightmap
showaxes: Show or hide the axes of map axes (their box, ticks and labels).
    showaxes('on' | 'off')
mfwdtran: Latitude and longitude as x and y in the current map's projection.
    [x, y] = mfwdtran(lat, lon)
    [x, y] = mfwdtran(mstruct, lat, lon)
minvtran: x and y in the current map's projection as latitude and longitude.
    [lat, lon] = minvtran(x, y)
    [lat, lon] = minvtran(mstruct, x, y)
plotm: Lines and markers on map axes, from latitude and longitude.
    plotm(lat, lon)
    plotm(lat, lon, LineSpec)
    plotm([lat lon], ...)
    h = plotm(...)
    * A line that crosses the edge of the map is broken there; what the map does not show is left out.
linem: Lines on map axes, from latitude and longitude.
    h = linem(lat, lon, Name, Value, ...)
scatterm: Markers on map axes, with sizes and colours, from latitude and longitude.
    h = scatterm(lat, lon, sz, c)
textm: Text on map axes at latitude and longitude.
    h = textm(lat, lon, txt)
patchm: A filled polygon on map axes.
    h = patchm(lat, lon, color)
fillm: A filled polygon on map axes.
    h = fillm(lat, lon, color)
surfm: A grid of values on map axes, coloured through the colormap.
    h = surfm(lat, lon, Z)
pcolorm: A grid of values on map axes, coloured through the colormap.
    h = pcolorm(lat, lon, Z)
contourm: Contour lines of a grid on map axes.
    contourm(lat, lon, Z)
    contourm(lat, lon, Z, levels)
    contourm(Z, R, ...)
    [C, h] = contourm(...)
geoshow: Show geographic data: lines, points, polygons, shapefile features or rasters.
    geoshow(lat, lon)
    geoshow(lat, lon, 'DisplayType', 'point' | 'line' | 'polygon')
    geoshow(S)
    geoshow(filename)
    geoshow(Z, R)
    geoshow(lat, lon, Z)
    * On map axes the data are projected; on other axes longitude is x and latitude y. S is a struct array as shaperead gives (Lat and Lon, or X and Y), each feature drawn as its Geometry says; a polygon is one patch, its holes left open.
    * geoshow('landareas.shp'), and worldlakes, worldrivers and worldcities: the world's land, lakes, rivers and cities from Natural Earth (see shaperead).
mapshow: Show data in map (projected) coordinates.
    mapshow(x, y)
    mapshow(S)
    mapshow(filename)
    mapshow(A, R)
geoaxes: Geographic axes: longitude across, latitude up, ticks in degrees with their hemispheres.
    gx = geoaxes
    gx = geoaxes('Basemap', name)
    gx = geoaxes(Name, Value, ...)
    * The aspect is the one of the middle latitude. There is no basemap until one is named (see geobasemap).
geoplot: Lines in geographic axes, from latitude and longitude.
    geoplot(lat, lon)
    geoplot(lat, lon, LineSpec)
    h = geoplot(gx, ...)
geoscatter: Markers in geographic axes, from latitude and longitude.
    geoscatter(lat, lon)
    geoscatter(lat, lon, sz, c)
    h = geoscatter(...)
geobubble: Bubbles in geographic axes, their areas growing with sizes.
    geobubble(lat, lon, sizedata)
    geobubble(lat, lon, sizedata, colordata)
    geobubble(..., 'Basemap', name)
geolimits: The latitude and longitude limits of geographic axes.
    geolimits(latlim, lonlim)
    [latlim, lonlim] = geolimits
    geolimits('auto')
geobasemap: The basemap under geographic axes: a map from the web, or land and water.
    geobasemap(name)
    geobasemap(gx, name)
    name = geobasemap
    gx.Basemap = name
    * Axes have none ('none') until a program names one. Only then is it fetched, only for what the axes show, and kept for the session.
    * streets: OpenStreetMap's map; streets-light and streets-dark: the same in light or dark greys; topographic: OpenTopoMap; satellite: Sentinel-2 cloudless 2016 by EOX; colorterrain and grayterrain: shaded relief from ASTER GDEM, and landcover: MODIS land cover, both from NASA GIBS; darkwater, grayland and bluegreen: Natural Earth's land and lakes in two colours.
    * Each is drawn with its attribution in the lower right corner of the axes, and saved with the figure. The maps from the web end at 85.05° north and south.
addCustomBasemap: Add a basemap of map tiles from a web address of your choosing.
    addCustomBasemap(name, url)
    addCustomBasemap(name, url, 'Attribution', text, 'DisplayName', label, 'MaxZoomLevel', z)
    * url has ${z}, ${x} and ${y} in it (or {z}, {x} and {y}) for the zoom level, column and row of a tile, as OpenStreetMap's tiles are numbered. The server must allow pages of other sites to use its tiles (CORS), or they are not drawn. MaxZoomLevel is 18 unless given.
removeCustomBasemap: Remove a basemap added with addCustomBasemap.
    removeCustomBasemap(name)
georefcells: A reference for a raster of cells in latitude and longitude.
    R = georefcells(latlim, lonlim, rasterSize)
    R = georefcells()
georefpostings: A reference for a raster of postings (samples) in latitude and longitude.
    R = georefpostings(latlim, lonlim, rasterSize)
    R = georefpostings()
georasterref: A geographic raster reference from properties.
    R = georasterref('RasterSize', [m n], 'LatitudeLimits', latlim, 'LongitudeLimits', lonlim)
    R = georasterref(..., 'RasterInterpretation', 'cells' | 'postings', 'ColumnsStartFrom', 'north' | 'south')
maprefcells: A reference for a raster of cells in projected x and y.
    R = maprefcells(xlim, ylim, rasterSize)
    R = maprefcells()
maprefpostings: A reference for a raster of postings in projected x and y.
    R = maprefpostings(xlim, ylim, rasterSize)
    R = maprefpostings()
geographicToIntrinsic: Latitude and longitude as fractional column and row of a raster.
    [xi, yi] = geographicToIntrinsic(R, lat, lon)
worldToIntrinsic: Projected x and y as fractional column and row of a raster.
    [xi, yi] = worldToIntrinsic(R, x, y)
geointerp: Values of a geographic raster at latitudes and longitudes.
    v = geointerp(A, R, lat, lon)
    v = geointerp(A, R, lat, lon, 'nearest' | 'linear' | 'cubic')
    * NaN outside the raster.
shaperead: The features of a shapefile as a struct array.
    S = shaperead(filename)
    S = shaperead(filename, 'UseGeoCoords', true)
    [S, A] = shaperead(...)
    S = shaperead(..., 'RecordNumbers', k, 'BoundingBox', [xmin ymin; xmax ymax], 'Selector', {@(v) ..., 'Field'}, 'Attributes', {'Field'})
    * Each feature has Geometry, BoundingBox, X and Y (Lon and Lat with UseGeoCoords), NaN after each part, and its attributes from the .dbf file.
    * landareas, worldlakes, worldrivers and worldcities (with or without .shp), when no file of that name is found, are Natural Earth's land, lakes, rivers and lake centre lines (all at 1:50m) and populated places (1:110m), public domain. They are fetched from jsDelivr the first time a program asks. Their one attribute is Name, for the lakes, rivers and cities.
shapeinfo: What a shapefile holds: its shape type, bounding box, number of features and attributes.
    info = shapeinfo(filename)
    * landareas, worldlakes, worldrivers and worldcities are Natural Earth's, as for shaperead.
shapewrite: Write a struct array of features to a shapefile (.shp, .shx and .dbf).
    shapewrite(S, filename)
    * One Geometry for all (Point, MultiPoint, Line or Polygon); fields of numbers or text become attributes.
readgeoraster: Read a GeoTIFF file: its values and their raster reference.
    [A, R] = readgeoraster(filename)
    [A, R, cmap] = readgeoraster(filename)
geotiffread: Read a GeoTIFF file (as readgeoraster).
    [A, R] = geotiffread(filename)
geotiffinfo: What a GeoTIFF file holds: its size, model type and spatial reference.
    info = geotiffinfo(filename)

# ---- symbolic math ------------------------------------------------------------------------------------------
sym: A symbolic number, variable or matrix.
    x = sym('x')
    x = sym('x', 'real')
    A = sym('a', [2 3])
    v = sym(0.1)
    v = sym(pi)
    v = sym(M, flag)
    * A double becomes the exact number it stands for: p/q, p*pi/q or sqrt(p)/q when it is one of those to the last bit ('r', the default), else the double's own binary fraction ('f'); 'd' gives a decimal of digits places. Symbols are complex unless assumed otherwise (real, positive, integer, rational). sym('a', [2 3]) names its elements a1_1, a1_2, ...; a vector's a1, a2, ....
    * Symbolic values take the operators (+ - * / \ ^ and their element-wise forms, comparisons that make equations, & | ~), indexing and assignment, and these functions of numbers: sin, cos, tan and the other trigonometric and hyperbolic functions and their inverses, exp, log, log2, log10, sqrt, abs, sign, real, imag, conj, angle, floor, ceil, round, fix, mod, rem, gamma, factorial, nchoosek, erf, erfc, besselj and its kin, atan2, nthroot, gcd, lcm, max, min, sum, prod, cumsum, cumprod, det, inv, trace, rank, eig, null, rref, expm, kron, dot, cross, norm, reshape, repmat, fliplr, flipud, diag, triu, tril, diff, gradient, factor, compose, symvar, char, string, double, single, logical, isequal, isreal, isprime, disp, fplot, ezplot, fsurf, fmesh and fcontour.
syms: Make symbolic variables and functions in the workspace.
    syms x y z
    syms x real
    syms a b positive
    syms f(x) g(x, y)
    syms a [1 3]
    syms x clear
    syms
    * syms f(x) makes x and the symbolic function f of x; f(x) = expression gives it a formula. syms alone lists the symbolic variables.
str2sym: A symbolic expression or equation from text in the language's syntax.
    e = str2sym('x^2 + sin(y)')
    e = str2sym('x + y == 3')
symfun: A symbolic function from a formula and its inputs.
    f = symfun(x^2 + y, [x y])
    * A symbolic function is also made by assigning: f(x, y) = x^2 + y. f(2, 3) gives its value; argnames(f) and formula(f) its parts.
vpa: Numbers to many significant digits (variable-precision arithmetic).
    v = vpa(x)
    v = vpa(x, d)
    * d is the number of significant digits (digits, 32 to begin with). A double is first recognized as sym recognizes it, so vpa(pi) is pi itself to d digits.
digits: The significant digits vpa uses.
    digits(d)
    d = digits
    old = digits(d)
poly2sym: A symbolic polynomial from its coefficients, highest power first.
    p = poly2sym([1 -2 3])
    p = poly2sym(c, x)
sym2poly: The coefficients of a polynomial in one variable, highest power first, as doubles.
    c = sym2poly(p)
piecewise: A symbolic expression with a value for each condition.
    y = piecewise(x < 0, -x, x)
    y = piecewise(cond1, val1, cond2, val2, ..., otherwise)
    * The first condition that holds gives the value; without an otherwise value the rest is NaN.
int: Integrals of symbolic expressions.
    F = int(f)
    F = int(f, x)
    F = int(f, a, b)
    F = int(f, x, a, b)
    F = int(..., 'Hold', true)
    * The variable is symvar(f, 1) unless given. An integral that has no closed form is shown unevaluated as int(...); 'Hold', true keeps it so.
limit: The limit of a symbolic expression.
    L = limit(f, x, a)
    L = limit(f, a)
    L = limit(f)
    L = limit(f, x, a, 'left')
    L = limit(f, x, a, 'right')
    * Without a side, the limit from both sides, NaN when they differ; limit(f) is the limit at 0.
taylor: The Taylor polynomial of a symbolic expression.
    T = taylor(f)
    T = taylor(f, x)
    T = taylor(f, x, a)
    T = taylor(..., 'Order', n)
    T = taylor(..., 'ExpansionPoint', a)
    * The terms up to the power n-1 (n is 6 unless given), about a (0 unless given).
series: The series of a symbolic expression about a point, with negative and fractional powers when it has them.
    S = series(f, x)
    S = series(f, x, a)
    S = series(..., 'Order', n)
    sys = series(sys1, sys2)
    * Of models: sys1 then sys2, as sys2*sys1.
symsum: Symbolic sums.
    F = symsum(f, k, a, b)
    F = symsum(f, k)
    * symsum(f, k) is the indefinite sum: F(k) with F(k+1) - F(k) = f(k), from 0. b may be Inf.
symprod: Symbolic products.
    F = symprod(f, k, a, b)
jacobian: The Jacobian matrix of symbolic functions.
    J = jacobian(f, v)
    * Row i is the gradient of f(i) with respect to the variables in v.
hessian: The Hessian matrix of a symbolic expression.
    H = hessian(f, v)
divergence: The divergence of a vector field: of arrays on a grid, or symbolic.
    div = divergence(X, Y, U, V)
    div = divergence(U, V)
    div = divergence(X, Y, Z, U, V, W)
    d = divergence(V, X)
    * Of arrays: dU/dx + dV/dy (+ dW/dz) by the differences gradient takes, x along the columns and y down the rows (unit spacing without X, Y, Z).
curl: The curl of a vector field: of arrays on a grid, or symbolic of three components.
    [curlz, cav] = curl(X, Y, U, V)
    [curlx, curly, curlz, cav] = curl(X, Y, Z, U, V, W)
    cav = curl(U, V)
    c = curl(V, X)
    * cav is the angular velocity: half the curl along the flow; with one output it is all curl gives of arrays.
laplacian: The Laplacian of a symbolic expression (the sum of its second derivatives), or the Laplacian matrix of a graph.
    L = laplacian(f, x)
    L = laplacian(G)
    * For a graph, a sparse matrix: the degrees on the diagonal, -1 where two nodes are joined (weights, parallel edges and self-loops are not counted).
simplify: A simpler form of a symbolic expression, or a graph without parallel edges and self-loops.
    s = simplify(e)
    s = simplify(e, 'IgnoreAnalyticConstraints', true)
    * 'IgnoreAnalyticConstraints' allows rules that hold for positive reals, as log(a*b) = log(a) + log(b) and sqrt(x^2) = x.
    H = simplify(G)
    H = simplify(G, method)
    H = simplify(G, 'keepselfloops')
    * For a graph: one edge for each pair of nodes joined, its weight the sum of theirs ('min', 'max', 'mean' or 'first' instead), and no self-loops.
simplifyFraction: A symbolic fraction with its numerator and denominator cancelled.
    s = simplifyFraction(e)
expand: Multiply out products and powers, and expand functions of sums.
    s = expand(e)
    s = expand(e, 'ArithmeticOnly', true)
collect: Collect the terms of a symbolic expression by powers of a variable.
    s = collect(e)
    s = collect(e, x)
combine: Combine terms with the same function: powers, logs, sin and cos, ...
    s = combine(e)
    s = combine(e, target)
    * target is 'powers' (the default), 'exp', 'log', 'sqrt', 'sincos', 'sinhcosh', 'gamma' or 'atan'.
horner: A polynomial in Horner's nested form.
    s = horner(p)
    s = horner(p, x)
rewrite: An expression rewritten in terms of other functions.
    s = rewrite(e, 'exp')
    * Targets: exp, log, sin, cos, tan, cot, sqrt, sincos, sinh, cosh, tanh, sinhcosh, asin, acos, atan, acot, asinh, acosh, atanh, heaviside, piecewise.
partfrac: The partial fractions of a rational expression.
    s = partfrac(e, x)
    s = partfrac(e, x, 'FactorMode', 'full')
numden: The numerator and denominator of a symbolic expression.
    [n, d] = numden(e)
coeffs: The coefficients of a polynomial.
    c = coeffs(p)
    c = coeffs(p, x)
    [c, t] = coeffs(p, x)
    c = coeffs(p, x, 'All')
    * Without 'All', the nonzero coefficients from the lowest power up, and t their terms; with 'All', every coefficient from the highest power down.
children: The operands of a symbolic expression, in a cell array.
    c = children(e)
has: Whether a symbolic expression contains a subexpression.
    tf = has(e, sub)
lhs: The left side of a symbolic equation or inequality.
    L = lhs(eqn)
rhs: The right side of a symbolic equation or inequality.
    R = rhs(eqn)
isolate: An equation rearranged to have a variable alone on its left.
    e = isolate(eqn, x)
argnames: The input variables of a symbolic function.
    v = argnames(f)
formula: The formula of a symbolic function, as a symbolic expression; of a fit or fittype, as text.
    e = formula(f)
finverse: The inverse of a symbolic function of one variable.
    g = finverse(f)
    g = finverse(f, x)
subs: Substitute values or expressions for symbolic variables.
    s = subs(e, old, new)
    s = subs(e, new)
    s = subs(e)
    s = subs(e, {x, y}, {1, 2})
    * old and new may be arrays or cells of the same size. A scalar expression with an array of values gives an array. subs(e) takes the values of the variables in the workspace; subs(e, new) replaces symvar(e, 1).
solve: Solve equations symbolically; or solve an ode object.
    S = solve(eqn, x)
    S = solve(eqns, vars)
    [x, y] = solve(eqns, [x y])
    S = solve(..., 'Real', true)
    S = solve(..., 'ReturnConditions', true)
    S = solve(F, tf)
    S = solve(F, t0, tf)
    S = solve(F, tspan)
    S = solve(F, ..., 'Refine', k)
    * An expression counts as expression == 0. For one variable the solutions come as a column; for several, a struct with a field for each variable, or one output for each. Solutions must agree with the variables' assumptions. With 'ReturnConditions', families of solutions come with their parameters (k) and conditions. 'MaxDegree' (3 unless given) is the highest degree of polynomial solved by radicals; higher ones give root(...).
    * solve(F, ...) of an ode object: its solution from InitialTime, at the solver's steps (or at the times of tspan when it has more than two); S.Time is a row, S.Solution a column for each time.
vpasolve: Solve equations numerically, to digits significant digits.
    S = vpasolve(eqn, x)
    S = vpasolve(eqn, x, x0)
    S = vpasolve(eqn, x, [a b])
    S = vpasolve(eqns, vars, x0)
    * A polynomial in one variable gives all its roots; anything else one root, from x0 (0 unless given) or within [a b].
dsolve: Solve ordinary differential equations symbolically.
    y = dsolve(eqn)
    y = dsolve(eqn, cond)
    S = dsolve(eqns, conds)
    [y1, y2] = dsolve(eqns, conds)
    * The unknowns are symbolic functions: syms y(t); dsolve(diff(y, t) == -y, y(0) == 1). A condition on a derivative uses the derivative as a function: Dy = diff(y); Dy(0) == 0. Free constants are C1, C2, ... For systems, a struct with a field for each unknown (in alphabetical order), or one output for each.
laplace: The Laplace transform.
    F = laplace(f)
    F = laplace(f, transVar)
    F = laplace(f, var, transVar)
    * From t to s unless given (to z when the variable is s).
ilaplace: The inverse Laplace transform.
    f = ilaplace(F)
    f = ilaplace(F, var, transVar)
    * From s to t unless given; the result holds for t > 0 (no heaviside(t) factor).
fourier: The Fourier transform: the integral of f(x)*exp(-1i*w*x) over x.
    F = fourier(f)
    F = fourier(f, var, transVar)
ifourier: The inverse Fourier transform: the integral of F(w)*exp(1i*w*x) over w, divided by 2*pi.
    f = ifourier(F)
    f = ifourier(F, var, transVar)
ztrans: The z-transform: the sum of f(n)*z^(-n) from n = 0.
    F = ztrans(f)
    F = ztrans(f, var, transVar)
iztrans: The inverse z-transform of a rational function.
    f = iztrans(F)
    f = iztrans(F, var, transVar)
assume: Set what is assumed about symbolic variables (replacing what was before).
    assume(x > 0)
    assume(x, 'real')
    assume([x y], 'integer')
    assume(x, 'clear')
    * The assumptions are 'real', 'positive', 'integer', 'rational', 'clear', or conditions such as x > 0, x ~= 0, in(x, 'integer') and other inequalities; solve keeps only the solutions that agree.
assumeAlso: Add to what is assumed about symbolic variables.
    assumeAlso(x < 10)
    assumeAlso(x, 'integer')
assumptions: What is assumed about symbolic variables.
    a = assumptions
    a = assumptions(x)
isAlways: Whether a symbolic condition holds for every value of its variables.
    tf = isAlways(cond)
    tf = isAlways(cond, 'Unknown', 'false' | 'true' | 'error')
    * When it cannot be decided, the answer is false with a warning, unless 'Unknown' says otherwise.
latex: The LaTeX form of a symbolic expression.
    s = latex(e)
pretty: Print a symbolic expression in two-dimensional form.
    pretty(e)
matlabFunction: A function handle (or a function file) computing a symbolic expression with numbers.
    f = matlabFunction(e)
    f = matlabFunction(e, 'Vars', [x y])
    f = matlabFunction(e1, e2, 'File', 'name')
    * The inputs are symvar(e) in order unless 'Vars' gives them; the operators are element-wise, so the handle takes arrays.
fimplicit: The curve where f(x, y) = 0.
    fimplicit(f)
    fimplicit(f, [xmin xmax])
    fimplicit(f, [xmin xmax ymin ymax])
    h = fimplicit(...)
    * f is a function handle of two inputs, or a symbolic expression or equation.
fplot3: A curve in 3-D given by x(t), y(t) and z(t).
    fplot3(xt, yt, zt)
    fplot3(xt, yt, zt, [tmin tmax])
heaviside: The step function: 0 below zero, 1 above, 1/2 at zero.
    y = heaviside(x)
dirac: The Dirac delta: Inf at zero, 0 elsewhere; symbolic for sym input.
    y = dirac(x)
    y = dirac(n, x)
sinc: sin(pi*x)/(pi*x), 1 at zero.
    y = sinc(x)
lambertw: The Lambert W function: w with w*exp(w) = x.
    w = lambertw(x)
    w = lambertw(k, x)
zeta: The Riemann zeta function.
    z = zeta(s)
kroneckerDelta: 1 where its arguments are equal, 0 elsewhere.
    d = kroneckerDelta(m, n)

# ---- optimization and integration ------------------------------------------------------------
fzero: A root of a function of one variable.
    x = fzero(fun, x0)
    x = fzero(fun, [a b])
    x = fzero(fun, x0, options)
    [x, fval, exitflag, output] = fzero(...)
fminbnd: The minimum of a function of one variable on an interval.
    x = fminbnd(fun, a, b)
    x = fminbnd(fun, a, b, options)
    [x, fval, exitflag, output] = fminbnd(...)
fminsearch: The minimum of a function of several variables, by the Nelder-Mead simplex (no derivatives).
    x = fminsearch(fun, x0)
    x = fminsearch(fun, x0, options)
    [x, fval, exitflag, output] = fminsearch(...)
fminunc: The minimum of a smooth function of several variables, without constraints.
    x = fminunc(fun, x0)
    x = fminunc(fun, x0, options)
    x = fminunc(problem)
    [x, fval, exitflag, output, grad, hessian] = fminunc(...)
    * Algorithm 'quasi-newton' (BFGS) or 'trust-region' (needs SpecifyObjectiveGradient, fun then giving [f, g]). exitflag: 1 first-order optimality below OptimalityTolerance, 2 the steps too small to go on, 0 MaxIterations or MaxFunctionEvaluations reached, -1 stopped by an output function, -3 below ObjectiveLimit.
fmincon: The minimum of a function under bounds and linear or nonlinear constraints.
    x = fmincon(fun, x0, A, b)
    x = fmincon(fun, x0, A, b, Aeq, beq, lb, ub)
    x = fmincon(fun, x0, A, b, Aeq, beq, lb, ub, nonlcon)
    x = fmincon(fun, x0, A, b, Aeq, beq, lb, ub, nonlcon, options)
    x = fmincon(problem)
    [x, fval, exitflag, output, lambda, grad, hessian] = fmincon(...)
    * A*x <= b, Aeq*x = beq, lb <= x <= ub; [c, ceq] = nonlcon(x) with c <= 0 and ceq = 0 (and their gradients as third and fourth outputs with SpecifyConstraintGradient). lambda holds the Lagrange multipliers: lower, upper, ineqlin, eqlin, ineqnonlin, eqnonlin. exitflag -2: no feasible point found.
fsolve: Solve a system of nonlinear equations F(x) = 0.
    x = fsolve(fun, x0)
    x = fsolve(fun, x0, options)
    x = fsolve(problem)
    [x, fval, exitflag, output, jacobian] = fsolve(...)
    * Algorithm 'trust-region-dogleg' (Powell's hybrid method), 'trust-region' or 'levenberg-marquardt'; with SpecifyObjectiveGradient fun gives [F, J]. exitflag 1: solved; -2: stopped where F is not zero.
lsqnonlin: Nonlinear least squares: the x that minimizes sum(fun(x).^2).
    x = lsqnonlin(fun, x0)
    x = lsqnonlin(fun, x0, lb, ub)
    x = lsqnonlin(fun, x0, lb, ub, options)
    x = lsqnonlin(fun, x0, lb, ub, A, b, Aeq, beq, nonlcon, options)
    [x, resnorm, residual, exitflag, output, lambda, jacobian] = lsqnonlin(...)
lsqcurvefit: Fit the parameters of a function to data by nonlinear least squares.
    x = lsqcurvefit(fun, x0, xdata, ydata)
    x = lsqcurvefit(fun, x0, xdata, ydata, lb, ub)
    x = lsqcurvefit(fun, x0, xdata, ydata, lb, ub, options)
    x = lsqcurvefit(fun, x0, xdata, ydata, lb, ub, A, b, Aeq, beq, nonlcon, options)
    [x, resnorm, residual, exitflag, output, lambda, jacobian] = lsqcurvefit(...)
    * fun(x, xdata) is fitted to ydata; residual is fun(x, xdata) - ydata.
lsqlin: Linear least squares under linear constraints and bounds: the x that minimizes norm(C*x - d).
    x = lsqlin(C, d, A, b)
    x = lsqlin(C, d, A, b, Aeq, beq, lb, ub)
    x = lsqlin(C, d, A, b, Aeq, beq, lb, ub, x0, options)
    [x, resnorm, residual, exitflag, output, lambda] = lsqlin(...)
lsqnonneg: Linear least squares with x >= 0.
    x = lsqnonneg(C, d)
    x = lsqnonneg(C, d, options)
    [x, resnorm, residual, exitflag, output, lambda] = lsqnonneg(...)
    * lambda is C'*(d - C*x) where x is 0, and 0 where x is positive.
quadprog: Quadratic programming: the x that minimizes 1/2*x'*H*x + f'*x under linear constraints and bounds.
    x = quadprog(H, f)
    x = quadprog(H, f, A, b)
    x = quadprog(H, f, A, b, Aeq, beq, lb, ub)
    x = quadprog(H, f, A, b, Aeq, beq, lb, ub, x0, options)
    x = quadprog(problem)
    [x, fval, exitflag, output, lambda] = quadprog(...)
    * exitflag -6: H is not positive semidefinite (the problem is not convex) with the default 'interior-point-convex' algorithm.
linprog: Linear programming: minimize f'*x under linear constraints and bounds.
    x = linprog(f, A, b)
    x = linprog(f, A, b, Aeq, beq, lb, ub)
    x = linprog(f, A, b, Aeq, beq, lb, ub, options)
    x = linprog(problem)
    [x, fval, exitflag, output, lambda] = linprog(...)
    * exitflag 1 optimal, 0 a limit reached, -2 infeasible, -3 unbounded.
intlinprog: Mixed-integer linear programming: linprog with some variables whole numbers.
    x = intlinprog(f, intcon, A, b)
    x = intlinprog(f, intcon, A, b, Aeq, beq, lb, ub)
    x = intlinprog(f, intcon, A, b, Aeq, beq, lb, ub, x0, options)
    x = intlinprog(problem)
    [x, fval, exitflag, output] = intlinprog(...)
    * intcon lists the variables (by index) that must be integers. exitflag 1 optimal, 2 stopped at a limit with a feasible point, 0 stopped with none, -2 infeasible, -3 unbounded.
fminimax: Make the largest of several objectives as small as possible.
    x = fminimax(fun, x0)
    x = fminimax(fun, x0, A, b, Aeq, beq, lb, ub, nonlcon, options)
    [x, fval, maxfval, exitflag, output, lambda] = fminimax(...)
    * fun returns a vector; with AbsoluteMaxObjectiveCount k the first k count by their absolute values.
fgoalattain: Bring several objectives to their goals: the smallest gamma with fun(x) - weight*gamma <= goal.
    x = fgoalattain(fun, x0, goal, weight)
    x = fgoalattain(fun, x0, goal, weight, A, b, Aeq, beq, lb, ub, nonlcon, options)
    [x, fval, attainfactor, exitflag, output, lambda] = fgoalattain(...)
    * A weight of 0 makes its goal a hard limit; with EqualityGoalCount k the first k objectives are to meet their goals exactly.
optimoptions: Options for a solver, by name and value.
    options = optimoptions('fmincon')
    options = optimoptions(@fmincon, 'Name', value, ...)
    options = optimoptions(oldoptions, 'Name', value, ...)
    options = optimoptions('fminunc', oldoptions)
    * Shown without a semicolon it lists the options set and the defaults. options.Name reads and sets one. Display: 'off', 'iter', 'final' or 'notify'. OutputFcn and PlotFcn take functions stop = f(x, optimValues, state), called at 'init', each 'iter' and 'done'; returning true stops the solver (exitflag -1).
    * The global solvers ga, particleswarm, simulannealbnd, patternsearch, surrogateopt and gamultiobj take their options this way too (PopulationSize, SwarmSize, InitialTemperature, MeshTolerance, MaxFunctionEvaluations, ...).
resetoptions: Options back to their defaults.
    options = resetoptions(options, 'Name')
    options = resetoptions(options, {'Name1', 'Name2'})
optimplotfval: A plot function for the solvers: the objective's value at each iteration.
    options = optimoptions(solver, 'PlotFcn', @optimplotfval)
    * Its kin: optimplotx (the current point as bars), optimplotfirstorderopt, optimplotfunccount, optimplotconstrviolation, optimplotstepsize and optimplotresnorm. Several in a cell share the window, one plot each.
optimplotx: A plot function for the solvers: the current point as bars.
    options = optimoptions(solver, 'PlotFcn', @optimplotx)
optimplotfirstorderopt: A plot function for the solvers: the first-order optimality at each iteration.
    options = optimoptions(solver, 'PlotFcn', @optimplotfirstorderopt)
optimplotfunccount: A plot function for the solvers: the function evaluations so far.
    options = optimoptions(solver, 'PlotFcn', @optimplotfunccount)
optimplotconstrviolation: A plot function for the constrained solvers: the largest constraint violation.
    options = optimoptions(solver, 'PlotFcn', @optimplotconstrviolation)
optimplotstepsize: A plot function for the solvers: the length of each step.
    options = optimoptions(solver, 'PlotFcn', @optimplotstepsize)
optimplotresnorm: A plot function for the least-squares solvers: the sum of squares at each iteration.
    options = optimoptions(solver, 'PlotFcn', @optimplotresnorm)
optimset: Make or change a structure of options for the solvers.
    options = optimset('Name', value, ...)
    options = optimset(oldopts, 'Name', value, ...)
    options = optimset('fminsearch')
optimget: An option's value from an options structure.
    v = optimget(options, 'Name')
    v = optimget(options, 'Name', default)
integral: A definite integral, by adaptive quadrature.
    q = integral(fun, a, b)
    q = integral(fun, a, b, 'RelTol', r, 'AbsTol', t)
    q = integral(fun, a, b, 'ArrayValued', true)
    q = integral(fun, a, b, 'Waypoints', w)
    * Complex limits or waypoints make a path of straight segments in the complex plane (a contour integral). The result is single when a limit or a waypoint is.
    * fun takes a vector and returns a vector of the same size; Inf is a limit too.
integral2: A double integral; the inner limits may be functions.
    q = integral2(fun, xmin, xmax, ymin, ymax)
integral3: A triple integral.
    q = integral3(fun, xmin, xmax, ymin, ymax, zmin, zmax)
quad: A definite integral by adaptive Simpson quadrature (older; integral is preferred).
    q = quad(fun, a, b)
    q = quad(fun, a, b, tol)
    q = quad(fun, a, b, tol, trace, p1, p2, ...)
    [q, fcnt] = quad(...)
    * p1, p2, ... are passed to fun after x; fcnt is the number of evaluations of fun.
quadl: A definite integral by adaptive Lobatto quadrature (older; integral is preferred).
    q = quadl(fun, a, b)
quadgk: A definite integral by adaptive Gauss-Kronrod quadrature.
    q = quadgk(fun, a, b)
    [q, errbnd] = quadgk(fun, a, b)
    q = quadgk(fun, a, b, 'RelTol', r, 'AbsTol', t, 'Waypoints', w, 'ArrayValued', true)
quad2d: A double integral over a region with curved limits.
    q = quad2d(fun, a, b, c, d)
dblquad: A double integral over a rectangle (older; integral2 is preferred).
    q = dblquad(fun, xmin, xmax, ymin, ymax)
triplequad: A triple integral over a box (older; integral3 is preferred).
    q = triplequad(fun, xmin, xmax, ymin, ymax, zmin, zmax)

# ---- differential equations ------------------------------------------------------------------
ode45: Solve a nonstiff ODE system y' = f(t, y) by the Dormand-Prince Runge-Kutta pair of orders 5 and 4: the first solver to try.
    [t, y] = ode45(odefun, tspan, y0)
    [t, y] = ode45(odefun, tspan, y0, options)
    sol = ode45(...)
    [t, y, te, ye, ie] = ode45(..., options)
    * odefun(t, y) returns a column; tspan with more than two values asks for the solution at those times.
    * Each of the solvers takes the options odeset makes; a mass matrix M(t, y) y' = f(t, y) is solved for y' at each evaluation by the nonstiff ones.
ode23: Solve a nonstiff ODE system by the Bogacki-Shampine Runge-Kutta pair of orders 3 and 2, for loose tolerances.
    [t, y] = ode23(odefun, tspan, y0)
    [t, y] = ode23(odefun, tspan, y0, options)
ode113: Solve a nonstiff ODE system by Adams-Bashforth-Moulton formulas of variable step and order (1 to 12), for tight tolerances or a costly odefun.
    [t, y] = ode113(odefun, tspan, y0)
    [t, y] = ode113(odefun, tspan, y0, options)
    * Predict, evaluate, correct, evaluate: two evaluations of odefun a step. The order and the step are chosen together from error estimates at the neighbouring orders (Shampine and Gordon's method).
ode78: Solve a nonstiff ODE system by Verner's Runge-Kutta pair of orders 8 and 7, for tight tolerances.
    [t, y] = ode78(odefun, tspan, y0)
    [t, y] = ode78(odefun, tspan, y0, options)
    * Values between the steps come from an interpolant of order 7, whose extra stages are evaluated only for the steps they are asked of.
ode89: Solve a nonstiff ODE system by Verner's Runge-Kutta pair of orders 9 and 8, for very tight tolerances.
    [t, y] = ode89(odefun, tspan, y0)
    [t, y] = ode89(odefun, tspan, y0, options)
    * Values between the steps come from an interpolant of order 8.
ode15s: Solve a stiff ODE system, or a differential-algebraic one (a singular mass matrix), by the numerical differentiation formulas of orders 1 to 5.
    [t, y] = ode15s(odefun, tspan, y0)
    [t, y] = ode15s(odefun, tspan, y0, options)
    * MaxOrder (1 to 5) caps the order; BDF 'on' takes the backward differentiation formulas instead of the NDFs.
    * With a singular mass matrix the algebraic part of y0 is first moved until the algebraic equations hold.
ode23s: Solve a stiff ODE system by the modified Rosenbrock pair of orders 2 and 3, for loose tolerances.
    [t, y] = ode23s(odefun, tspan, y0)
    [t, y] = ode23s(odefun, tspan, y0, options)
    * The Jacobian is formed at every step; the mass matrix, if any, must be constant.
ode23t: Solve a moderately stiff ODE system, or a differential-algebraic one, by the trapezoidal rule.
    [t, y] = ode23t(odefun, tspan, y0)
    [t, y] = ode23t(odefun, tspan, y0, options)
    * The rule does not damp: a component far stiffer than the step rings about its value, so ode15s or ode23tb suit a very stiff problem better.
ode23tb: Solve a stiff ODE system by TR-BDF2: a trapezoidal stage, then a second-order backward differentiation stage, for loose tolerances.
    [t, y] = ode23tb(odefun, tspan, y0)
    [t, y] = ode23tb(odefun, tspan, y0, options)
ode15i: Solve an implicit system F(t, y, y') = 0, an implicit ODE or a differential-algebraic one of index 1, by the backward differentiation formulas of orders 1 to 5.
    [t, y] = ode15i(odefun, tspan, y0, yp0)
    [t, y] = ode15i(odefun, tspan, y0, yp0, options)
    sol = ode15i(...)
    * y0 and yp0 must satisfy F(t0, y0, yp0) = 0, and decic finds values that do. For an implicit ODE (dF/dy' nonsingular) yp0 is corrected to fit y0, with a warning.
    * The Jacobian option is a function returning [dFdy, dFdyp], or a cell {dFdy, dFdyp}; MaxOrder caps the order.
decic: Initial conditions that satisfy F(t0, y0, yp0) = 0, for ode15i.
    [y0new, yp0new] = decic(odefun, t0, y0, fixed_y0, yp0, fixed_yp0)
    [y0new, yp0new, resnrm] = decic(odefun, t0, y0, fixed_y0, yp0, fixed_yp0, options)
    * fixed_y0 and fixed_yp0 hold (with 1) components at the values given; the others change as little as least squares can. resnrm is the norm of F at the result.
odeset: Make or change the options for the ODE solvers.
    options = odeset('RelTol', 1e-6, 'AbsTol', 1e-9, ...)
    options = odeset(oldopts, 'Name', value, ...)
    * Among the names: RelTol, AbsTol, MaxStep, InitialStep, Refine, Events, Jacobian, NonNegative, OutputFcn, OutputSel, Mass, MStateDependence, MassSingular, MaxOrder, BDF.
    * Mass is a matrix, or a function of t (MStateDependence 'none', or a function of one input) or of t and y; MassSingular ('yes', 'no' or 'maybe') says whether to look for a singular one.
    * OutputFcn is called with 'init', then after each step with its times and the states OutputSel names (all, unless given), then 'done'; a true answer stops the solution. A solver asked for no output plots with odeplot.
    * Stats, Vectorized and NormControl are accepted and change nothing.
odeget: An option's value from an ODE options structure.
    v = odeget(options, 'Name')
    v = odeget(options, 'Name', default)
odeplot: The output function that plots each solution component against time as the solver goes.
    options = odeset('OutputFcn', @odeplot)
    * The solvers use it when no output is asked for: ode45(@f, [0 10], y0) plots the solution.
deval: Evaluate the solution structure of an ODE, BVP or DDE solver at new points.
    y = deval(sol, t)
    y = deval(sol, t, idx)
    [y, yp] = deval(sol, t)
    * sol comes from an ODE solver, bvp4c, bvp5c, dde23 or ddesd; yp, the derivative, from those but the ODE solvers.
odextend: Carry the solution structure of an ODE solver on to a later time.
    sol = odextend(sol, odefun, tfinal)
    sol = odextend(sol, [], tfinal)
    sol = odextend(sol, odefun, tfinal, y0)
    sol = odextend(sol, odefun, tfinal, y0, options)

# ---- text ------------------------------------------------------------------------------------
char: A character array, from numbers (character codes), strings or cells of text.
    c = char(x)
    c = char(s1, s2, ...)
    * char(p) of a Python object (see pyrun): its str().
string: A string array, from text, numbers or cells.
    s = string(x)
    * string(p) of a Python object (see pyrun): its str(); a list of str a string array.
strings: A string array of empty strings.
    s = strings(m, n)
cellstr: A cell array of character vectors.
    C = cellstr(A)
sprintf: Format data as text.
    s = sprintf(format, a1, a2, ...)
    * The format is used again until every value is written: sprintf('%d,', 1:3) is '1,2,3,'.
num2str: A number as text, with about four significant decimals by default.
    s = num2str(x)
    s = num2str(x, precision)
    s = num2str(x, format)
int2str: Numbers rounded to integers, as text.
    s = int2str(x)
mat2str: A matrix as text in the language's own brackets.
    s = mat2str(A)
    s = mat2str(A, precision)
str2num: Evaluate text as an expression and return its value.
    x = str2num(s)
    [x, ok] = str2num(s)
str2double: Text as a double; NaN when it is not a number.
    x = str2double(s)
strcat: Join text; trailing spaces of char arrays are dropped.
    s = strcat(s1, s2, ...)
strvcat: Character arrays stacked as rows, padded with spaces, empty ones left out.
    S = strvcat(t1, t2, ...)
strjoin: Join the text of a cell array with a separator (a space by default).
    s = strjoin(C)
    s = strjoin(C, delimiter)
strsplit: Split text at a separator (white space by default).
    C = strsplit(s)
    C = strsplit(s, delimiter)
split: Split strings at a separator (white space by default).
    parts = split(s)
    parts = split(s, delimiter)
join: Join the strings of an array with a separator; or two tables by their keys.
    s = join(parts)
    s = join(parts, delimiter)
    T = join(A, B)
    T = join(A, B, 'Keys', keys)
    * For tables: A with B's other variables added, each row of A matched to the row of B with its keys (the variables of the same name unless given); every key of A must be in B.
splitlines: Split text at line breaks.
    lines = splitlines(s)
strtrim: Remove white space from both ends.
    t = strtrim(s)
strip: Remove white space (or a given character) from the ends.
    t = strip(s)
    t = strip(s, 'left' | 'right' | 'both')
    t = strip(s, side, character)
deblank: Remove trailing white space and null characters.
    t = deblank(s)
blanks: A row of spaces.
    s = blanks(n)
pad: Pad text to a length with spaces (or another character).
    t = pad(s)
    t = pad(s, n)
    t = pad(s, n, 'left' | 'right' | 'both')
strjust: Shift the text of a character array to the right, left or centre.
    t = strjust(s)
    t = strjust(s, 'left' | 'right' | 'center')
upper: Text in capitals.
    t = upper(s)
lower: Text in small letters.
    t = lower(s)
reverse: Text backwards.
    t = reverse(s)
strlength: The number of characters of each string.
    n = strlength(s)
strcmp: True when two texts are identical.
    tf = strcmp(s1, s2)
strcmpi: True when two texts are identical, ignoring case.
    tf = strcmpi(s1, s2)
strncmp: True when the first n characters match.
    tf = strncmp(s1, s2, n)
strncmpi: True when the first n characters match, ignoring case.
    tf = strncmpi(s1, s2, n)
contains: True when text contains a pattern.
    tf = contains(s, pattern)
    tf = contains(s, pat)
    tf = contains(s, pattern, 'IgnoreCase', true)
startsWith: True when text starts with a pattern.
    tf = startsWith(s, pattern)
endsWith: True when text ends with a pattern.
    tf = endsWith(s, pattern)
matches: True when text equals a pattern (or one of several).
    tf = matches(s, pattern)
strfind: The starting indices of a pattern in text.
    k = strfind(s, pattern)
strmatch: The rows of a char matrix (or elements of a cell array) that start with some text, or (with 'exact') are that text.
    k = strmatch(s, list)
    k = strmatch(s, list, 'exact')
    * The blanks that pad the rows of a char matrix never count.
    * A cell array of any shape is taken down its columns: k are linear indices.
count: How many times a pattern occurs in text.
    n = count(s, pattern)
strtok: The first token of text, and the rest.
    token = strtok(s)
    [token, rest] = strtok(s, delimiters)
strrep: Replace every occurrence of a substring.
    t = strrep(s, old, new)
replace: Replace every occurrence of one or more substrings.
    t = replace(s, old, new)
erase: Delete every occurrence of a substring.
    t = erase(s, pattern)
extractBefore: The text before a position or a pattern.
    t = extractBefore(s, pos)
    t = extractBefore(s, pattern)
extractAfter: The text after a position or a pattern.
    t = extractAfter(s, pos)
    t = extractAfter(s, pattern)
extractBetween: The text between two positions or patterns.
    t = extractBetween(s, start, stop)
insertAfter: Insert text after a position or a pattern.
    t = insertAfter(s, pos, new)
insertBefore: Insert text before a position or a pattern.
    t = insertBefore(s, pos, new)
regexp: Match a regular expression.
    [tok, mat] = regexp(s, expr, 'tokens', 'match')
    startIndex = regexp(s, expr)
    names = regexp(s, expr, 'names')
    parts = regexp(s, expr, 'split')
    t = regexp(s, expr, 'match', 'once')
    * Outputs come in the order of the keywords: 'match', 'tokens', 'names', 'start', 'end', 'split', 'tokenExtents'.
regexpi: Match a regular expression, ignoring case.
    [...] = regexpi(s, expr, ...)
regexprep: Replace the matches of a regular expression; $1, $2 ... refer to tokens.
    t = regexprep(s, expr, replace)
    t = regexprep(s, expr, replace, 'once')
    t = regexprep(s, expr, replace, 'ignorecase')
regexptranslate: Escape text for use in a regular expression, or turn a wildcard into one.
    t = regexptranslate('escape', s)
    t = regexptranslate('wildcard', s)
isspace: True for white-space characters.
    tf = isspace(s)
isletter: True for letters.
    tf = isletter(s)
isstrprop: True for characters of a category: 'alpha', 'digit', 'alphanum', 'upper', 'lower', 'wspace', 'punct', 'cntrl', 'xdigit'.
    tf = isstrprop(s, category)
istext: True for a char array or a string array.
    tf = istext(x)
dec2bin: Integers as binary digits.
    s = dec2bin(d)
    s = dec2bin(d, n)
    * A negative number is written in two's complement, in 8, 16, 32 or 64 bits.
bin2dec: Binary digits as an integer.
    d = bin2dec(s)
dec2hex: Integers as hexadecimal digits.
    s = dec2hex(d)
    s = dec2hex(d, n)
hex2dec: Hexadecimal digits as an integer.
    d = hex2dec(s)
dec2base: Integers as digits in a base from 2 to 36.
    s = dec2base(d, base)
    s = dec2base(d, base, n)
base2dec: Digits in a base from 2 to 36 as an integer.
    d = base2dec(s, base)
num2hex: The 16 hexadecimal digits of a double's IEEE bits.
    s = num2hex(x)
hex2num: A double from the hexadecimal digits of its IEEE bits.
    x = hex2num(s)
compose: Format data into a string array, one string per row of values.
    s = compose(format, a1, a2, ...)
newline: The line feed character, char(10).
    c = newline
sscanf: Read formatted data from text.
    A = sscanf(s, format)
    A = sscanf(s, format, sizeA)
    [A, count, errmsg, nextindex] = sscanf(...)
validatestring: The one of several valid texts that a text abbreviates, or an error.
    s = validatestring(str, validStrings)
convertCharsToStrings: Character vectors (and cells of them) as strings; anything else as it is.
    [a, b, ...] = convertCharsToStrings(a, b, ...)
convertStringsToChars: Strings as character vectors; anything else as it is.
    [a, b, ...] = convertStringsToChars(a, b, ...)

# ---- cells, structs and maps ------------------------------------------------------------------
cell: A cell array of empty matrices.
    C = cell(n)
    C = cell(m, n)
    * cell(p) of a Python object (see pyrun): the items of a list, tuple or other sequence (a dict its values), each converted as Python values coming back are.
cellfun: Call a function on the contents of every cell.
    A = cellfun(fun, C)
    A = cellfun(fun, C1, C2, ...)
    B = cellfun(fun, C, 'UniformOutput', false)
    [A, B] = cellfun(fun, C)
    A = cellfun('isempty', C)
num2cell: Each element of an array in a cell of its own.
    C = num2cell(A)
    C = num2cell(A, dims)
cell2mat: The contents of a cell array joined into one array.
    A = cell2mat(C)
cell2struct: A struct array from a cell array and field names.
    s = cell2struct(C, fields, dim)
struct2cell: The values of a struct's fields as a cell array.
    C = struct2cell(s)
struct: A struct, from field names and values; a cell value makes a struct array.
    s = struct('field1', value1, 'field2', value2, ...)
    s = struct()
    s = struct([])
    * struct('f', {1, 2}) is a 1-by-2 struct array; struct('f', {{1, 2}}) holds the cell itself.
    * struct(p) of a Python object (see pyrun): a dict as a struct, its keys the field names.
fieldnames: The names of a struct's fields, as a cell column.
    names = fieldnames(s)
isfield: True when a struct has a field (or which of several it has).
    tf = isfield(s, name)
    tf = isfield(s, names)
rmfield: Remove fields from a struct.
    s = rmfield(s, name)
    s = rmfield(s, names)
setfield: Set a field, s.(name) = value, as a function.
    s = setfield(s, name, value)
getfield: A field's value, s.(name), as a function.
    v = getfield(s, name)
orderfields: Put a struct's fields in alphabetical (or another) order.
    s = orderfields(s1)
    [s, perm] = orderfields(s1, order)
arrayfun: Call a function on every element of arrays.
    A = arrayfun(fun, X)
    A = arrayfun(fun, X1, X2, ...)
    B = arrayfun(fun, X, 'UniformOutput', false)
structfun: Call a function on every field of a scalar struct.
    A = structfun(fun, s)
    B = structfun(fun, s, 'UniformOutput', false)
dictionary: Keys and the values they stand for, kept in the order they were put in.
    d = dictionary(keys, values)
    d = dictionary(k1, v1, k2, v2, ...)
    d = dictionary()
    * d(keys) looks keys up, d(keys) = values puts them in (a new dictionary: it is a value, not a handle), d(keys) = [] takes them out, d{keys} gives the contents of cell values. Keys are text (kept as strings), numbers or logicals; the values are all of one class. dictionary() has no types until something is put in.
insert: A dictionary with keys and values put in.
    d = insert(d, keys, values)
lookup: Values of a dictionary, with one for keys it has not.
    v = lookup(d, keys)
    v = lookup(d, keys, FallbackValue=x)
numEntries: How many keys a dictionary has.
    n = numEntries(d)
isConfigured: True when a dictionary has its key and value types (something was put in).
    tf = isConfigured(d)
types: The classes of a dictionary's keys and values, as strings.
    [keyType, valueType] = types(d)
entries: A dictionary's keys and values as a table (or a struct array or a cell).
    T = entries(d)
    S = entries(d, 'struct')
    C = entries(d, 'cell')
containers.Map: A map from keys (text or numbers) to values.
    M = containers.Map()
    M = containers.Map(keys, values)
    M = containers.Map('KeyType', 'char', 'ValueType', 'any')
    * M(key) reads and sets values; M.Count is the number of keys; M is a handle: copies share it.
keys: The keys of a map, sorted, as a cell row (of a dictionary: in their order, as a column).
    k = keys(M)
values: The values of a map, in the order of its keys, or those of some keys (of a dictionary likewise, as a column).
    v = values(M)
    v = values(M, keySet)
isKey: True when a map (or a dictionary) has a key (or which of several it has).
    tf = isKey(M, key)
remove: Remove keys from a map; for a dictionary, a dictionary without them.
    remove(M, key)
    d = remove(d, keys)
deal: Copy inputs to outputs, one by one or all from one.
    [a, b, c] = deal(x, y, z)
    [a, b, c] = deal(x)
    * [s.field] = deal(value) sets a field of every element of a struct array.
iscell: True for a cell array.
    tf = iscell(x)
iscellstr: True for a cell array whose cells all hold character vectors.
    tf = iscellstr(x)
isstruct: True for a struct.
    tf = isstruct(x)

# ---- types -----------------------------------------------------------------------------------
class: The name of a value's class.
    c = class(x)
isa: True when a value is of a class or of a category ('numeric', 'float', 'integer').
    tf = isa(x, classname)
isnumeric: True for numbers (double, single and the integer classes).
    tf = isnumeric(x)
isfloat: True for double and single.
    tf = isfloat(x)
isinteger: True for the integer classes (not for whole numbers stored as double).
    tf = isinteger(x)
islogical: True for logical values.
    tf = islogical(x)
ischar: True for a character array.
    tf = ischar(x)
isstring: True for a string array.
    tf = isstring(x)
isobject: True for an object of a class (a map, an exception).
properties: The public properties of an object or class.
    properties(obj)
    properties('ClassName')
    p = properties(obj)
methods: The methods of an object or class.
    methods(obj)
    methods('ClassName')
    m = methods(obj)
ismethod: Whether an object's class has a method of that name.
    tf = ismethod(obj, 'name')
addlistener: Hear an event of an object: the callback runs when notify raises it.
    L = addlistener(obj, 'EventName', @(src, evt) ...)
    * The callback is given the object and the event data (Source, EventName and any fields given to notify). L.Enabled turns it off and on; delete(L) removes it.
listener: Hear an event of an object (as addlistener).
    L = listener(obj, 'EventName', callback)
notify: Raise an event of an object: its listeners' callbacks run.
    notify(obj, 'EventName')
    notify(obj, 'EventName', eventData)
plabSuperCall: What a class's obj@Super(args) and method@Super(obj, args) become (PyLAB writes it; not called by hand).
    obj = plabSuperCall('Super', obj, args)
    tf = isobject(x)
double: Convert to double precision.
    y = double(x)
    * double(p) of a Python object (see pyrun): its numbers (a list, tuple, range or NumPy array; a 1-D one a row).
single: Convert to single precision.
    y = single(x)
int8: Convert to 8-bit signed integers, rounding and saturating.
    y = int8(x)
uint8: Convert to 8-bit unsigned integers, rounding and saturating.
    y = uint8(x)
int16: Convert to 16-bit signed integers, rounding and saturating.
    y = int16(x)
uint16: Convert to 16-bit unsigned integers, rounding and saturating.
    y = uint16(x)
int32: Convert to 32-bit signed integers, rounding and saturating.
    y = int32(x)
uint32: Convert to 32-bit unsigned integers, rounding and saturating.
    y = uint32(x)
int64: Convert to 64-bit signed integers, rounding and saturating.
    y = int64(x)
uint64: Convert to 64-bit unsigned integers, rounding and saturating.
    y = uint64(x)
logical: Convert numbers to logical values (nonzero is true).
    tf = logical(x)
cast: Convert to a class given by name.
    y = cast(x, classname)
    y = cast(x, 'like', p)
typecast: Read the bytes of numbers as another numeric class, without converting.
    y = typecast(x, classname)
func2str: The text of a function handle.
    s = func2str(fh)
symvar: The variables an expression uses, sorted.
    names = symvar('a*x + exp(-k*t)')
    * Other names are left out: i, j, pi, Inf, NaN, eps and the functions there are.
str2func: A function handle from its text.
    fh = str2func('name')
    fh = str2func('@(x) x.^2')
feval: Call a function by handle or by name.
    [y1, y2, ...] = feval(fun, x1, x2, ...)
    y = feval(f, x)
    * f may be a fit (from fit), evaluated at x.

# ---- programs and the workspace --------------------------------------------------------------
disp: Show a value without its name.
    disp(x)
display: Show a value with its name, as a statement without a semicolon does.
    display(x)
fprintf: Write formatted text to the Command Window or to a file.
    fprintf(format, a1, a2, ...)
    fprintf(fid, format, a1, a2, ...)
    n = fprintf(...)
error: Throw an error.
    error(msg)
    error(format, a1, a2, ...)
    error(identifier, format, a1, a2, ...)
    error(errstruct)
warning: Show a warning, or turn warnings on and off.
    warning(msg)
    warning(identifier, format, a1, ...)
    warning('off', identifier)
    warning('on', identifier)
    [msg, id] = lastwarn
lasterr: The message of the last error.
    msg = lasterr
lastwarn: The message (and identifier) of the last warning.
    [msg, id] = lastwarn
MException: An exception object, to throw.
    ME = MException(identifier, format, a1, ...)
    throw(ME)
throw: Throw an exception.
    throw(ME)
rethrow: Throw a caught exception again, its stack kept.
    rethrow(ME)
throwAsCaller: Throw an exception as if from the calling function.
    throwAsCaller(ME)
addCause: Add a cause to an exception.
    ME = addCause(ME, causeME)
getReport: The text of an exception, as the Command Window shows it.
    s = getReport(ME)
assert: Throw an error when a condition does not hold.
    assert(cond)
    assert(cond, msg)
    assert(cond, identifier, format, a1, ...)
onCleanup: An object that runs a function when it is cleared or goes out of scope.
    c = onCleanup(@() fclose(fid))
exist: Whether a name is a variable (1), a file (2), a builtin (5) or a folder (7); 0 when none.
    n = exist(name)
    n = exist(name, 'var' | 'file' | 'dir' | 'builtin')
clear: Remove variables (or functions, globals, everything).
    clear
    clear name1 name2
    clear -regexp pattern
    clear global
    clear all
    clear functions
clearvars: Remove variables, optionally keeping some.
    clearvars
    clearvars -except name1 name2
who: List the variables.
    who
    who x y*
    who -file filename
    names = who(...)
    * -file lists the variables of a MAT-file instead of the workspace's; names, with * as a wildcard, keep only those that match.
whos: List the variables with their sizes, bytes and classes.
    whos
    whos x y*
    whos -file filename
    s = whos(...)
    * -file lists the variables of a MAT-file; a variable that cannot be read is listed from its header.
eval: Run text as code.
    eval(expression)
    eval(try_expression, catch_expression)
    x = eval(expression)
evalin: Run text as code in the caller's or the base workspace.
    evalin('base' | 'caller', expression)
    x = evalin('base', expression)
evalc: Run text as code and return what it wrote.
    s = evalc(expression)
assignin: Set a variable in the caller's or the base workspace.
    assignin('base' | 'caller', name, value)
inputname: The name of a variable passed as an input, or '' for an expression.
    s = inputname(k)
mfilename: The name of the program file the code runs in; '' in the Command Window.
    name = mfilename
    p = mfilename('fullpath')
    * 'fullpath' gives the file's folder and name, without .m.
nargin: The number of inputs a function was called with (or takes, for nargin(fun)).
    n = nargin
    n = nargin(fun)
nargout: The number of outputs a function was called with.
    n = nargout
    n = nargout(fun)
narginchk: An error unless the number of inputs is between two bounds.
    narginchk(minArgs, maxArgs)
nargoutchk: An error unless the number of outputs is between two bounds.
    nargoutchk(minArgs, maxArgs)
validateattributes: An error unless a value has the given classes and attributes.
    validateattributes(x, classes, attributes)
    validateattributes(x, classes, attributes, funcName, varName)
    validateattributes(x, classes, attributes, funcName, varName, argIndex)
    * Classes are class names, or 'numeric', 'float' and 'integer'.
    * Attributes: '2d', '3d', 'row', 'column', 'scalar', 'scalartext', 'vector', 'square', 'diag', 'nonempty', 'nonsparse', 'binary', 'even', 'odd', 'integer', 'real', 'finite', 'nonnan', 'nonnegative', 'nonzero', 'positive', 'increasing', 'decreasing', 'nondecreasing', 'nonincreasing', and with a value 'size' (NaN for any), 'numel', 'ncols', 'nrows', 'ndims', '>', '>=', '<', '<='.
isvarname: True for text that is a valid variable name.
    tf = isvarname(s)
iskeyword: True for a keyword of the language, or the list of keywords.
    tf = iskeyword(s)
    k = iskeyword
genvarname: A valid variable name made from text, unlike some names to avoid.
    name = genvarname(s)
    name = genvarname(s, exclusions)
matlab.lang.makeValidName: Valid variable names made from text.
    names = matlab.lang.makeValidName(s)
    names = matlab.lang.makeValidName(s, 'ReplacementStyle', style, 'Prefix', p)
    [names, modified] = matlab.lang.makeValidName(...)
builtin: Call the built-in function of a name, even when a file of that name shadows it.
    [y1, ...] = builtin(name, x1, ...)
functions: Information about a function handle.
    s = functions(fh)
input: Ask for input in the Command Window.
    x = input(prompt)
    s = input(prompt, 's')
    * Without 's' the answer is evaluated as an expression; with it, it is returned as text.
keyboard: Stop the program here and hand the Command Window over (K>>) until dbcont or dbquit.
    keyboard
format: How the Command Window shows numbers.
    format
    format short | long | shortE | longE | shortG | longG | rat | hex
    format compact | loose
clc: Empty the Command Window.
    clc
more: Accepted, with no effect: the Command Window does not page its output.
    more on | off
echo: Accepted, with no effect.
    echo on | off
diary: The Command Window's commands and output copied to a file.
    diary
    diary on
    diary off
    diary filename
    * diary alone turns it on or off; the file is 'diary' in the current folder unless named, and is added to. Links are written as their text.
sound: Play samples through the page's sound.
    sound(y)
    sound(y, fs)
    * y is a vector (one channel) or a matrix of two columns (left and right), between -1 and 1; fs is samples a second, 8192 unless given.
    * The program goes on while it plays.
soundsc: Play samples scaled to fill the loudness range.
    soundsc(y)
    soundsc(y, fs)
    soundsc(y, fs, [low high])
    * The data's own range, or [low high], becomes -1 to 1.
beep: A short tone through the page's sound.
    beep
    beep on | off
    s = beep
    * beep off silences it, and s = beep is 'on' or 'off'.
profile: The time spent in each function and line of programs.
    profile on
    profile off
    profile resume
    profile clear
    profile viewer
    p = profile('info')
    s = profile('status')
    * profile on starts afresh, resume goes on adding. viewer (or report) shows each function's calls, total and self time and its slowest lines, as links. Built-in functions are counted in the lines that call them. Programs run slower while profiled.
exit: Stop the program; the page itself is closed with its browser tab.
    exit
quit: Stop the program; the page itself is closed with its browser tab.
    quit
help: The help of a function or a program file.
    help name
    text = help('name')
    * A program file's help is its first block of comments; help(mfilename) is a program's own.
version: The interpreter's version, as text.
    v = version
ver: The interpreter and the Python, NumPy and SciPy that run it.
    ver
computer: The kind of computer: 'PYODIDE' here (Python in the browser).
    c = computer
ispc: False here.
    tf = ispc
ismac: False here (the programs run in Pyodide, whatever the computer).
    tf = ismac
isunix: True here: the file system is a Unix one.
    tf = isunix
isdeployed: False.
    tf = isdeployed
usejava: False: there is no Java here.
    tf = usejava(feature)
matlabroot: The folder of the interpreter's own files.
    p = matlabroot
userpath: The home folder of your files.
    p = userpath
getenv: An environment variable of the Python process.
    v = getenv(name)
setenv: Set an environment variable of the Python process.
    setenv(name, value)
web: Open a web address in a new browser tab.
    web(url)

# ---- dates and time --------------------------------------------------------------------------
tic: Start a stopwatch.
    tic
    t0 = tic
toc: The seconds since tic.
    toc
    t = toc
    t = toc(t0)
pause: Wait for a number of seconds, or for a key press in the Command Window.
    pause(seconds)
    pause
    pause(player)
    * pause(player) stops an audioplayer (or audiorecorder) where it is; resume goes on.
cputime: The processor time used, in seconds.
    t = cputime
clock: The date and time as [year month day hour minute seconds].
    c = clock
now: The date and time as a serial date number.
    t = now
date: Today's date as text, dd-mmm-yyyy.
    s = date
datenum: Serial date numbers: days from the year 0, with fractions for the time.
    n = datenum(Y, M, D)
    n = datenum(Y, M, D, h, m, s)
    n = datenum(datevector)
    n = datenum(text)
    n = datenum(text, format)
datestr: Dates as text.
    s = datestr(t)
    s = datestr(t, format)
    * format is a number from 0 to 31 or a pattern such as 'yyyy-mm-dd HH:MM:SS'.
datevec: Date vectors [year month day hour minute seconds] from serial numbers or text.
    v = datevec(t)
    [Y, M, D, h, m, s] = datevec(t)
etime: The seconds between two date vectors.
    e = etime(t1, t0)
weekday: The day of the week, 1 for Sunday to 7 for Saturday, and its name.
    [n, name] = weekday(t)
eomday: The last day of a month.
    d = eomday(year, month)
addtodate: Add an amount of a field (year, month, week, day, hour ...) to a serial date number.
    t = addtodate(t0, q, field)
leapyear: True for leap years.
    tf = leapyear(year)

# ---- datetime, duration and calendarDuration --------------------------------------------------------
datetime: Points in time, as values that print, compare and add as dates.
    t = datetime('now')
    t = datetime('today')
    t = datetime(y, mo, d)
    t = datetime(y, mo, d, h, mi, s)
    t = datetime(text)
    t = datetime(text, 'InputFormat', fmt)
    t = datetime(X, 'ConvertFrom', kind)
    t = datetime(..., 'Format', fmt, 'TimeZone', tz)
    * kind: 'datenum', 'posixtime', 'excel', 'excel1904', 'juliandate', 'modifiedjuliandate', 'yyyymmdd' or 'epochtime'.
    * Formats use letters: uuuu or yyyy (year), MM, MMM, MMMM (month), dd (day), eee, eeee (weekday), HH (hour), hh and a (12-hour clock), mm (minute), ss (second), SSS (fractions), with text in quotes, 'T'.
    * t.Year, t.Month, t.Day, t.Hour, t.Minute, t.Second read and set the parts; t.Format and t.TimeZone the display and the zone.
    * t2 - t1 is a duration; t + d adds a duration, a calendarDuration or a number of days.
NaT: Not-a-Time, a missing datetime.
    t = NaT
    t = NaT(m, n)
isdatetime: True for a datetime.
    tf = isdatetime(t)
isnat: True where a datetime is NaT.
    tf = isnat(t)
year: The year of each datetime.
    y = year(t)
month: The month of each datetime.
    m = month(t)
    names = month(t, 'name')
day: The day of each datetime.
    d = day(t)
    d = day(t, 'dayofweek')
    d = day(t, 'dayofyear')
    names = day(t, 'name')
hour: The hour of each datetime.
    h = hour(t)
minute: The minute of each datetime.
    m = minute(t)
second: The second of each datetime, with its fraction.
    s = second(t)
quarter: The quarter of the year of each datetime.
    q = quarter(t)
week: The week of the year (or of the month) of each datetime.
    w = week(t)
    w = week(t, 'weekofmonth')
ymd: The year, month and day of each datetime.
    [y, m, d] = ymd(t)
hms: The hour, minute and second of each datetime or duration.
    [h, m, s] = hms(t)
timeofday: The time since midnight of each datetime, as a duration.
    d = timeofday(t)
isweekend: True where a datetime falls on a Saturday or Sunday.
    tf = isweekend(t)
isbetween: True where datetimes lie between two others.
    tf = isbetween(t, lower, upper)
    tf = isbetween(t, lower, upper, 'open')
posixtime: Seconds since 1 January 1970 (UTC for zoned datetimes).
    p = posixtime(t)
juliandate: The Julian date of each datetime.
    jd = juliandate(t)
    mjd = juliandate(t, 'modifiedjuliandate')
exceltime: Excel's day number of each datetime.
    e = exceltime(t)
    e = exceltime(t, 1904)
convertTo: Datetimes as numbers of a kind.
    X = convertTo(t, kind)
    X = convertTo(t, 'epochtime', 'Epoch', t0, 'TicksPerSecond', n)
tzoffset: The offset of each datetime's time zone from UTC, as a duration.
    d = tzoffset(t)
dateshift: Move datetimes to the start or end of a unit, or to a day of the week.
    t2 = dateshift(t, 'start', unit)
    t2 = dateshift(t, 'end', unit)
    t2 = dateshift(t, 'start', unit, rule)
    t2 = dateshift(t, 'dayofweek', day)
    * unit: 'year', 'quarter', 'month', 'week', 'day', 'hour', 'minute', 'second'. rule: 'current', 'next', 'previous', or a number of units.
between: The calendar difference between datetimes, as a calendarDuration.
    d = between(t1, t2)
    d = between(t1, t2, components)
    * components from 'years', 'quarters', 'months', 'weeks', 'days' and 'time'.
caldiff: The calendar differences between consecutive datetimes.
    d = caldiff(t)
duration: Lengths of time.
    d = duration(h, m, s)
    d = duration(h, m, s, ms)
    d = duration(text)
    d = duration(..., 'Format', fmt)
    * Formats: 'hh:mm:ss', 'dd:hh:mm:ss', 'hh:mm', 'mm:ss' (each may end in .SSS), and 'y', 'd', 'h', 'm', 's' for one unit.
isduration: True for a duration.
    tf = isduration(d)
years: Durations of years (365.2425 days each), or a duration in years.
    d = years(x)
    x = years(d)
days: Durations of days, or a duration in days.
    d = days(x)
    x = days(d)
hours: Durations of hours, or a duration in hours.
    d = hours(x)
    x = hours(d)
minutes: Durations of minutes, or a duration in minutes.
    d = minutes(x)
    x = minutes(d)
seconds: Durations of seconds, or a duration in seconds.
    d = seconds(x)
    x = seconds(d)
milliseconds: Durations of milliseconds, or a duration in milliseconds.
    d = milliseconds(x)
    x = milliseconds(d)
calendarDuration: Lengths of time in calendar units: months and days, whose length depends on where they start.
    c = calendarDuration(y, mo, d)
    c = calendarDuration(y, mo, d, h, mi, s)
    c = calendarDuration(y, mo, d, t)
iscalendarduration: True for a calendarDuration.
    tf = iscalendarduration(c)
calyears: Calendar years, as a calendarDuration.
    c = calyears(n)
calquarters: Calendar quarters, as a calendarDuration.
    c = calquarters(n)
calmonths: Calendar months, as a calendarDuration.
    c = calmonths(n)
calweeks: Calendar weeks, as a calendarDuration.
    c = calweeks(n)
caldays: Calendar days, as a calendarDuration.
    c = caldays(n)

# ---- categorical arrays ----------------------------------------------------------------------------
categorical: Arrays whose elements are each one of a set of named categories, or undefined.
    c = categorical(data)
    c = categorical(data, valueset)
    c = categorical(data, valueset, catnames)
    c = categorical(..., 'Ordinal', true, 'Protected', true)
    * data is text (a cell array of character vectors, a string array) or numbers; the categories are its distinct values in sorted order, or valueset; missing values ('', <missing>, NaN) are undefined.
    * c == 'name' and c ~= 'name' compare with a category; <, <=, >, >= compare by the categories' order and need 'Ordinal'.
    * c(k) = 'name' adds the category unless the array is protected.
categories: The categories of a categorical array, as a column cell array of names.
    names = categories(c)
iscategorical: True for a categorical array.
    tf = iscategorical(c)
isordinal: True for a categorical array whose categories are ordered.
    tf = isordinal(c)
isprotected: True for a categorical array that takes no new categories by assignment.
    tf = isprotected(c)
isundefined: True where an element of a categorical array is in no category.
    tf = isundefined(c)
iscategory: True for each name that is a category of a categorical array.
    tf = iscategory(c, names)
countcats: How many elements are in each category.
    n = countcats(c)
    n = countcats(c, dim)
addcats: Categories added to a categorical array.
    c2 = addcats(c, names)
    c2 = addcats(c, names, 'Before', name)
    c2 = addcats(c, names, 'After', name)
removecats: Categories removed from a categorical array, their elements made undefined.
    c2 = removecats(c)
    c2 = removecats(c, names)
    * With no names, the categories no element is in.
mergecats: Categories made one.
    c2 = mergecats(c, oldcats)
    c2 = mergecats(c, oldcats, newcat)
renamecats: Categories renamed.
    c2 = renamecats(c, newnames)
    c2 = renamecats(c, oldnames, newnames)
reordercats: The categories put in another order.
    c2 = reordercats(c)
    c2 = reordercats(c, neworder)
    * With no order, alphabetical; neworder gives the names, or the categories' positions.
setcats: The categories set; elements of the others become undefined.
    c2 = setcats(c, newcats)
summary: The categories of a categorical array and their counts, or a table's variables in short.
    summary(c)
    summary(T)
    * For a table: each variable's size and class, its units and description, and its values in short (min, median and max, the categories' counts, how many are missing).

# ---- tables and timetables -------------------------------------------------------------------------
table: Columns of data of any class (variables), one row per observation, with names.
    T = table(var1, ..., varN)
    T = table(..., 'VariableNames', names, 'RowNames', rownames)
    T = table('Size', [n m], 'VariableTypes', types)
    T = table(results)
    * Variables are named after the variables given, else Var1, Var2, ...
    * T(rows, vars) is a table; T{rows, vars} the variables' data put together; T.Name a variable. rows and vars are numbers, logical masks, ':', or names (row names, variable names); vars may be vartype(type).
    * T.Name = x adds a variable; T(rows, :) = [] and T(:, vars) = [] delete; T(end+1, :) = {v1, ..., vN} adds a row; [T1; T2] and [T1, T2] concatenate.
    * T.Properties holds Description, UserData, DimensionNames, VariableNames, VariableDescriptions, VariableUnits and RowNames, each set by assignment (T.Properties.VariableNames{2} = 'x').
    * table(results) of test results (runtests): a row for each test, its Name, Passed, Failed, Incomplete, Duration and Details.
timetable: A table whose rows are points in time (datetimes or durations).
    TT = timetable(rowTimes, var1, ..., varN)
    TT = timetable(var1, ..., varN, 'RowTimes', rowTimes)
    TT = timetable(var1, ..., varN, 'SampleRate', fs)
    TT = timetable(var1, ..., varN, 'TimeStep', dt, 'StartTime', t0)
    * TT(t, :) picks rows by their times, TT(timerange(t1, t2), :) the rows from t1 up to t2; TT.Time (or the first dimension's name) are the row times.
    * TT.Properties also has RowTimes, StartTime, SampleRate and TimeStep.
istable: True for a table.
    tf = istable(T)
istimetable: True for a timetable.
    tf = istimetable(T)
istabular: True for a table or a timetable.
    tf = istabular(T)
height: The number of rows of a table, or of an array.
    n = height(T)
width: The number of variables of a table, or the number of columns of an array.
    n = width(T)
head: The first rows of a table or an array.
    T2 = head(T)
    T2 = head(T, k)
    * 8 rows unless k is given.
tail: The last rows of a table or an array.
    T2 = tail(T)
    T2 = tail(T, k)
vartype: Picks a table's variables of a type, in T(:, vartype(type)).
    s = vartype(type)
    * type: 'numeric', 'cellstr', or a class name such as 'logical', 'string', 'datetime', 'categorical'.
timerange: Picks the rows of a timetable between two times, in TT(timerange(t1, t2), :).
    r = timerange(t1, t2)
    r = timerange(t1, t2, intervalType)
    * intervalType: 'openright' (from t1 up to but not including t2; the default), 'closed', 'open', 'openleft'.
table2array: A table's variables put together as one array.
    A = table2array(T)
table2cell: A table's values as a cell array, one cell per row and variable.
    C = table2cell(T)
table2struct: A table as a struct array, one element per row.
    S = table2struct(T)
    S = table2struct(T, 'ToScalar', true)
    * With 'ToScalar', true: one struct whose fields are the variables.
struct2table: A struct array as a table, its fields the variables.
    T = struct2table(S)
    T = struct2table(S, 'RowNames', rownames)
cell2table: A cell array as a table, each column a variable.
    T = cell2table(C)
    T = cell2table(C, 'VariableNames', names, 'RowNames', rownames)
    * A column of numbers becomes a numeric variable; any other column stays a cell array.
array2table: A matrix as a table, each column a variable.
    T = array2table(A)
    T = array2table(A, 'VariableNames', names, 'RowNames', rownames)
table2timetable: A table as a timetable, a datetime or duration variable as its row times.
    TT = table2timetable(T)
    TT = table2timetable(T, 'RowTimes', times)
    * Without 'RowTimes', the first datetime or duration variable; 'RowTimes' may name a variable or give the times.
timetable2table: A timetable as a table, the row times its first variable.
    T = timetable2table(TT)
addvars: Variables added to a table.
    T2 = addvars(T, var1, ..., varN)
    T2 = addvars(..., 'Before', var)
    T2 = addvars(..., 'After', var)
    T2 = addvars(..., 'NewVariableNames', names)
removevars: Variables removed from a table.
    T2 = removevars(T, vars)
movevars: Variables moved within a table.
    T2 = movevars(T, vars, 'Before', var)
    T2 = movevars(T, vars, 'After', var)
    * With neither, to the end.
renamevars: Variables renamed.
    T2 = renamevars(T, vars, newnames)
splitvars: Each variable of several columns (or a table in a table) made one variable per column.
    T2 = splitvars(T)
    T2 = splitvars(T, vars)
mergevars: Variables put together as one, where the first of them stood.
    T2 = mergevars(T, vars)
    T2 = mergevars(T, vars, 'NewVariableName', name)
rows2vars: A table turned so that its rows become variables.
    T2 = rows2vars(T)
    * The variables' names are in the first new variable, OriginalVariableNames; the new variables are named after the row names, or Var1, Var2, ...
convertvars: Variables converted to another type.
    T2 = convertvars(T, vars, type)
    T2 = convertvars(T, vars, fh)
    * type: 'double', 'single', 'logical', an integer class, 'string', 'cellstr', 'char', 'categorical', 'datetime' or 'duration'; or a function handle applied to each variable.
varfun: A function applied to each variable of a table.
    T2 = varfun(fh, T)
    T2 = varfun(fh, T, 'InputVariables', vars)
    T2 = varfun(fh, T, 'GroupingVariables', vars)
    A = varfun(fh, T, 'OutputFormat', 'uniform')
    C = varfun(fh, T, 'OutputFormat', 'cell')
    * With grouping variables, once per group: a row per group, with its size in GroupCount. The results are named after the function and the variable (mean_x).
rowfun: A function applied to each row of a table, the variables as its inputs.
    T2 = rowfun(fh, T)
    T2 = rowfun(fh, T, 'InputVariables', vars, 'OutputVariableNames', names)
    T2 = rowfun(fh, T, 'GroupingVariables', vars)
    T2 = rowfun(fh, T, 'NumOutputs', n)
    A = rowfun(fh, T, 'OutputFormat', 'uniform')
    * With grouping variables, once per group, the group's rows as the inputs.
groupsummary: Statistics of a table's variables for each group of rows.
    G = groupsummary(T, groupvars)
    G = groupsummary(T, groupvars, method)
    G = groupsummary(T, groupvars, method, datavars)
    * method: 'mean', 'sum', 'min', 'max', 'range', 'median', 'mode', 'var', 'std', 'nnz', 'numel', 'nummissing', 'all', a function handle, or a list of them; missing values are left out.
    * A row per group (in sorted order), its size in GroupCount; the results named method_variable. Without datavars, every numeric variable that does not group.
innerjoin: The rows of two tables whose keys are in both, side by side.
    T = innerjoin(A, B)
    T = innerjoin(A, B, 'Keys', keys)
    T = innerjoin(A, B, 'LeftKeys', lk, 'RightKeys', rk)
    [T, ia, ib] = innerjoin(...)
    * The keys are the variables of the same name unless given; the result is sorted by the keys. Variables of the same name that are no keys get the inputs' names after them (or _left and _right).
outerjoin: The rows of two tables matched by their keys, with missing values where one has no match.
    T = outerjoin(A, B)
    T = outerjoin(A, B, 'Type', type)
    T = outerjoin(A, B, 'MergeKeys', true)
    [T, ia, ib] = outerjoin(...)
    * type: 'full' (the default), 'left', 'right'. MergeKeys makes each pair of keys one variable.
retime: A timetable at new row times, its values filled in or put together.
    TT2 = retime(TT, newTimes)
    TT2 = retime(TT, newTimes, method)
    TT2 = retime(TT, timeStep, method)
    TT2 = retime(TT, 'regular', method, 'TimeStep', dt)
    TT2 = retime(TT, 'regular', method, 'SampleRate', fs)
    TT2 = retime(..., 'Constant', c)
    * timeStep: 'yearly', 'quarterly', 'monthly', 'weekly', 'daily', 'hourly', 'minutely', 'secondly'.
    * Filling: 'fillwithmissing' (the default), 'fillwithconstant', 'previous', 'next', 'nearest', 'linear', 'spline', 'pchip', 'makima'.
    * Putting together the rows from each new time up to the next: 'mean', 'median', 'mode', 'sum', 'prod', 'min', 'max', 'count', 'firstvalue', 'lastvalue', or a function handle.
synchronize: Timetables side by side at common row times.
    TT = synchronize(TT1, TT2, ...)
    TT = synchronize(TT1, TT2, ..., newTimeBasis)
    TT = synchronize(TT1, TT2, ..., newTimeBasis, method)
    * newTimeBasis: 'union' (the default), 'intersection', 'commonrange', 'first', 'last', new times, or a time step as for retime; method as for retime.
isregular: True when a timetable's row times step evenly.
    tf = isregular(TT)
    tf = isregular(TT, unit)
    [tf, dt] = isregular(...)
    * unit: 'time' (the default), or 'years', 'quarters', 'months', 'weeks', 'days', 'hours', 'minutes', 'seconds' for steps of whole calendar units.
readtable: A table from a delimited text file or a spreadsheet.
    T = readtable(filename)
    T = readtable(filename, opts)
    T = readtable(filename, 'Delimiter', d, 'NumHeaderLines', n)
    T = readtable(filename, 'ReadVariableNames', false)
    T = readtable(filename, 'ReadRowNames', true)
    T = readtable(filename, 'Sheet', sheet)
    T = readtable(filename, 'TextType', 'string')
    T = readtable(filename, 'VariableNamingRule', 'preserve')
    * Text files (.csv, .txt, .dat) and .xlsx spreadsheets. The first row names the variables; each column becomes numbers, datetimes or text.
writetable: A table written to a delimited text file or a spreadsheet.
    writetable(T, filename)
    writetable(T, filename, 'Delimiter', d)
    writetable(T, filename, 'WriteVariableNames', false, 'WriteRowNames', true)
    writetable(T, filename, 'QuoteStrings', true)
    * .csv, .txt and .dat files are text, comma-separated unless 'Delimiter' says otherwise; .xlsx files are spreadsheets.

# ---- files and folders -----------------------------------------------------------------------
pwd: The current folder.
    p = pwd
cd: Change the current folder.
    cd folder
    cd ..
    p = cd
dir: The files and folders in a folder, with their dates and sizes.
    dir
    dir folder
    dir *.m
    listing = dir(name)
ls: The names of the files and folders in a folder.
    ls
    ls folder
what: The program files and MAT-files of a folder.
    what
    what folder
which: Where a function or file is found.
    which name
    p = which(name)
type: Show the text of a file.
    type filename
edit: Open a file in the Editor (a new script if it does not exist).
    edit
    edit filename
open: Open a file: program files in the Editor, MAT-files into the workspace, figure files as figures.
    open filename
    open(v)
    s = open('data.mat')
    h = open('plot.fig')
run: Run a script file, tests, or a global search.
    run filename
    results = run(suite)
    results = run(testCase)
    results = run(testCase, 'testName')
    results = run(runner, suite)
    [x, fval, exitflag, output, solutions] = run(ms, problem, k)
    [x, fval, exitflag, output, solutions] = run(gs, problem)
    * A test suite (testsuite), an object of a test class or a test runner first: the tests run, as runtests runs them.
    * A MultiStart or GlobalSearch object first: the local solver runs (see MultiStart and GlobalSearch).
mkdir: Make a folder.
    mkdir folder
    [status, msg] = mkdir(parent, folder)
rmdir: Remove a folder (with its contents when 's' is given).
    rmdir folder
    rmdir(folder, 's')
delete: Delete files, or graphics objects.
    delete filename
    delete(h)
copyfile: Copy a file or folder.
    copyfile(source, destination)
movefile: Move or rename a file or folder.
    movefile(source, destination)
zip: Compress files and folders into a zip file.
    zip(zipfile, files)
    zip(zipfile, files, rootfolder)
    entries = zip(...)
    * files is a name, a cell of names, or a pattern with * and ?; a folder brings everything in it. The entries are named by their paths from rootfolder (the current folder unless given), and .zip is added to a name with no extension.
unzip: Unpack a zip file.
    unzip(zipfile)
    unzip(zipfile, outputfolder)
    files = unzip(...)
    * The files go to outputfolder (the current folder unless given); an entry that would land outside it is left out, with a warning.
gzip: Compress files, each into a gzip file of its own (.gz added to its name).
    gzip(files)
    gzip(files, outputfolder)
    names = gzip(...)
gunzip: Unpack gzip files, each into a file of its name without .gz.
    gunzip(files)
    gunzip(files, outputfolder)
    names = gunzip(...)
tar: Put files and folders into a tar file, compressed with gzip when its name ends in .tgz or .tar.gz.
    tar(tarfile, files)
    tar(tarfile, files, rootfolder)
    entries = tar(...)
untar: Unpack a tar file, compressed or not.
    untar(tarfile)
    untar(tarfile, outputfolder)
    files = untar(...)
    * Only files and folders are unpacked; an entry that would land outside the folder is left out, with a warning.
fullfile: A path from its parts.
    p = fullfile(part1, part2, ...)
fileparts: The folder, name and extension of a path.
    [folder, name, ext] = fileparts(p)
filesep: The separator of folders in paths, '/'.
    c = filesep
pathsep: The separator of folders in the search path, ':'.
    c = pathsep
tempdir: A folder for temporary files.
    p = tempdir
tempname: A unique name for a temporary file.
    p = tempname
isfile: True when a file exists.
    tf = isfile(name)
isfolder: True when a folder exists.
    tf = isfolder(name)
isdir: True when a folder exists (older; isfolder is preferred).
    tf = isdir(name)
addpath: Add folders to the search path for functions.
    addpath(folder)
    addpath(folder1, folder2, ..., '-end')
rehash: Look again for the program files on the path.
    rehash
    * Files written or changed are seen at once anyway; programs that call rehash after writing one run as they are.
rmpath: Remove folders from the search path.
    rmpath(folder)
path: The search path, or set it.
    p = path
    path(newpath)
genpath: A folder and every folder under it, as a path.
    p = genpath(folder)
fopen: Open a file and get its identifier.
    fid = fopen(filename)
    fid = fopen(filename, permission)
    [fid, msg] = fopen(...)
    * permission is 'r' (the default), 'w', 'a', 'r+', 'w+' or 'a+'; add 't' for text or 'b' for binary.
fclose: Close an open file.
    fclose(fid)
    fclose('all')
fgetl: Read the next line of a file, without its line break (-1 at the end).
    line = fgetl(fid)
fgets: Read the next line of a file, with its line break (-1 at the end).
    line = fgets(fid)
fread: Read binary data from a file.
    A = fread(fid)
    A = fread(fid, sizeA, precision)
    [A, count] = fread(...)
fwrite: Write binary data to a file.
    count = fwrite(fid, A)
    count = fwrite(fid, A, precision)
fscanf: Read formatted data from a file.
    A = fscanf(fid, format)
    A = fscanf(fid, format, sizeA)
feof: True at the end of a file.
    tf = feof(fid)
ferror: The message of the last error on a file.
    msg = ferror(fid)
frewind: Go back to the start of a file.
    frewind(fid)
ftell: The position in a file, in bytes.
    p = ftell(fid)
fseek: Move to a position in a file.
    status = fseek(fid, offset, origin)
fileread: The whole text of a file.
    text = fileread(filename)
readlines: The lines of a text file, as a string column.
    lines = readlines(filename)
writelines: Write text to a file, one line per string.
    writelines(lines, filename)
textscan: Read columns of formatted data from a file or text.
    C = textscan(fid, format)
    C = textscan(text, format, N)
    C = textscan(text, format, 'Delimiter', ',', 'HeaderLines', 1)
    [C, position] = textscan(...)
    * %f %n read doubles, %f32 singles, %d %u int32 and uint32 (%d8 to %d64, %u8 to %u64 the others); %s a word (to a delimiter when there are delimiters), %q a word that may be in double quotes, %c characters, %[...] characters of a set; a width such as %4f reads at most that many characters; %*f skips a field; other text in the format must match.
    * Options: Delimiter, Whitespace, EndOfLine, HeaderLines, EmptyValue, TreatAsEmpty, CommentStyle, MultipleDelimsAsOne, CollectOutput, ReturnOnError, ExpChars, TextType.
textread: Read a file by applying a format again and again, over line ends; one output per field.
    words = textread(filename, '%s')
    [names, ages] = textread(filename, '%s %d', 'headerlines', 1)
    [a, b] = textread(filename, '%f %f', n, 'delimiter', ',')
    * %d %f %n %u read numbers (as doubles), %s a word, %q a word in double quotes, %c one character, %[...] characters of a set; %*s skips a field.
    * Options: delimiter, whitespace, headerlines, commentstyle ('matlab', 'shell', 'c', 'c++') and emptyvalue.
readmatrix: A numeric matrix from a text file of delimited numbers.
    A = readmatrix(filename)
    A = readmatrix(filename, 'NumHeaderLines', n)
writematrix: Write a matrix to a delimited text file.
    writematrix(A, filename)
    writematrix(A, filename, 'Delimiter', delim)
csvread: A numeric matrix from a comma-separated file (older; readmatrix is preferred).
    M = csvread(filename)
    M = csvread(filename, row, col)
csvwrite: Write a matrix to a comma-separated file (older; writematrix is preferred).
    csvwrite(filename, M)
dlmread: A numeric matrix from a delimited file (older; readmatrix is preferred).
    M = dlmread(filename)
    M = dlmread(filename, delimiter, row, col)
dlmwrite: Write a matrix to a delimited file (older; writematrix is preferred).
    dlmwrite(filename, M)
    dlmwrite(filename, M, delimiter)
readcell: A cell array of the values in a delimited text file, numbers and text.
    C = readcell(filename)
writecell: Write a cell array of numbers and text to a delimited file.
    writecell(C, filename)
load: Load variables from a MAT-file, or a matrix from a text file.
    load filename
    load filename x y
    load filename -mat
    S = load(filename)
    * MAT-files of versions 4, 6, 7 and 7.3 load, compressed or not. The names may hold * as a wildcard.
    * Tables, timetables, datetimes, durations, calendarDurations, categoricals and string arrays load as themselves, also inside cells and structs. A variable that cannot be read is left out with a warning and the others load: other objects are not read. Sparse matrices load sparse.
    * A text file of numbers loads as a variable named after the file; -mat reads a MAT-file of any name.
    * load coastlines, when no coastlines.mat is found, gives coastlat and coastlon: Natural Earth's coastline (1:110m, public domain), the lines parted by NaN. It is fetched from jsDelivr the first time a program asks.
save: Save variables to a MAT-file (or to a text file with -ascii).
    save filename
    save filename x y
    save(filename, 'x', 'y')
    save filename x -append
    save filename x -ascii
    * -append adds to what the file holds; it refuses, saving nothing, rather than lose a variable of the file it cannot read.
    * The file is of version 7 (compressed), or 6 or 4 when asked; -v7.3 also writes version 7. Tables, timetables, datetimes, durations, calendarDurations, categoricals and string arrays are saved as objects in the file (not in version 4); function handles and other objects are not saved.
matfile: The variables of a MAT-file, as a struct.
    m = matfile(filename)
importdata: The data of a file: a MAT-file's variables, or the numbers of a text file.
    A = importdata(filename)

# ---- line and area plots ---------------------------------------------------------------------
plot: Lines and markers in 2-D.
    plot(y)
    plot(x, y)
    plot(x, y, LineSpec)
    plot(x1, y1, x2, y2, ...)
    plot(..., 'Name', value)
    h = plot(...)
    plot(f, x, y)
    plot(f, x, y, 'residuals')
    h = plot(G)
    h = plot(G, LineSpec, 'Layout', method, 'Name', value)
    * LineSpec joins a line style (- -- : -.), a marker (o + * . x s d ^ v > < p h) and a colour (r g b c m y k w), e.g. 'r--o'. plot(f, x, y) draws a fit (from fit) over its data; 'residuals' plots the residuals. plot(G) draws a graph or digraph (see layout for the methods), giving a GraphPlot whose NodeColor, EdgeColor, MarkerSize, LineWidth, NodeLabel, EdgeLabel, NodeCData, ArrowSize, XData and YData can be set.
plot3: Lines and markers in 3-D.
    plot3(x, y, z)
    plot3(x, y, z, LineSpec)
line: Add a line to the current axes, without clearing them.
    line(x, y)
    line(x, y, z)
    h = line(..., 'Name', value)
semilogx: A plot with a logarithmic x axis.
    semilogx(x, y, ...)
semilogy: A plot with a logarithmic y axis.
    semilogy(x, y, ...)
loglog: A plot with both axes logarithmic.
    loglog(x, y, ...)
fplot: Plot a function of one variable over an interval.
    fplot(f)
    fplot(f, [xmin xmax])
    fplot(..., LineSpec)
ezplot: Plot a function of one variable (older; fplot is preferred).
    ezplot(f)
    ezplot(f, [xmin xmax])
scatter: Markers at points, with sizes and colours of their own.
    scatter(x, y)
    scatter(x, y, sz)
    scatter(x, y, sz, c)
    scatter(..., 'filled')
scatter3: Markers at points in 3-D.
    scatter3(x, y, z)
    scatter3(x, y, z, sz, c)
bubblechart: Bubbles at points, their areas growing with sizes.
    bubblechart(x, y, sz)
    bubblechart(x, y, sz, c)
    bubblechart(ax, ...)
    bubblechart(..., Name, Value)
    h = bubblechart(...)
    * The smallest size in the axes gets the smallest bubble and the largest the largest; bubblesize sets their diameters (1 and 20 points to begin with) and bubblelim the sizes they stand for. c is one colour (a name or an RGB triplet) for all, an RGB row for each bubble, or values mapped through the colormap. The bubbles' faces are see-through (MarkerFaceAlpha 0.6).
bubblechart3: Bubbles at points in 3-D, their areas growing with sizes.
    bubblechart3(x, y, z, sz)
    bubblechart3(x, y, z, sz, c)
    h = bubblechart3(...)
bubblesize: The diameters in points of the smallest and the largest bubbles in axes.
    r = bubblesize
    bubblesize([dmin dmax])
    bubblesize(ax, ...)
bubblelim: The sizes that the smallest and the largest bubbles in axes stand for.
    L = bubblelim
    bubblelim([lo hi])
    bubblelim('auto' | 'manual')
    m = bubblelim('mode')
    bubblelim(ax, ...)
    * In auto mode they are the smallest and largest sizes of the axes' bubble charts. Sizes outside the limits get the end bubbles.
bar: A bar chart; a matrix gives groups (or stacks) of bars.
    bar(y)
    bar(x, y)
    bar(..., width)
    bar(..., 'stacked')
barh: A bar chart with horizontal bars.
    barh(y)
    barh(x, y)
histogram: A histogram of data.
    histogram(X)
    histogram(X, nbins)
    histogram(X, edges)
    histogram(..., 'Normalization', 'probability' | 'pdf' | 'count')
    histogram(C)
    h = histogram(...)
    * For a categorical array C, a bar for each category with its count (or 'probability' or 'percentage'), the axis named by the categories; h is the bars.
hist: A histogram (older; histogram is preferred), or its counts.
    hist(y)
    hist(y, nbins)
    [counts, centers] = hist(y, ...)
area: Filled areas under lines; a matrix gives stacked areas.
    area(y)
    area(x, y)
fill: Filled polygons.
    fill(x, y, c)
fill3: Filled polygons in 3-D.
    fill3(x, y, z, c)
patch: Filled polygons from vertices, as a graphics object.
    patch(x, y, c)
    patch('Faces', F, 'Vertices', V, 'FaceColor', c)
    patch(fv)
    * fv is a struct of faces and vertices (as isosurface gives), with other properties as fields.
stairs: A stairstep plot.
    stairs(y)
    stairs(x, y)
stem: Values as stems from the axis, with markers at their ends.
    stem(y)
    stem(x, y)
    stem(..., 'filled')
errorbar: Lines with error bars.
    errorbar(y, err)
    errorbar(x, y, err)
    errorbar(x, y, neg, pos)
pie: A pie chart.
    pie(x)
    pie(x, explode)
    pie(x, labels)
polarplot: Lines in polar coordinates.
    polarplot(theta, rho)
    polarplot(theta, rho, LineSpec)
    polarplot(pax, theta, rho)
    * theta is in radians.
polarscatter: Markers at points in polar coordinates, with sizes and colours of their own.
    polarscatter(theta, rho)
    polarscatter(theta, rho, sz)
    polarscatter(theta, rho, sz, c)
    polarscatter(..., 'filled')
    polarscatter(pax, ...)
    h = polarscatter(...)
    * theta is in radians; sz and c as for scatter.
polarbubblechart: Bubbles at points in polar coordinates, their areas growing with sizes.
    polarbubblechart(theta, rho, sz)
    polarbubblechart(theta, rho, sz, c)
    polarbubblechart(pax, ...)
    h = polarbubblechart(...)
    * theta is in radians; sz and c as for bubblechart.
polaraxes: Polar axes: angles round a circle, radii out from its middle.
    pax = polaraxes
    pax = polaraxes(parent)
    pax = polaraxes('Name', value, ...)
    * subplot(m, n, p, polaraxes) puts them in a tile of a grid; polarplot and polarscatter draw in them. Their class is matlab.graphics.axis.PolarAxes and their Type 'polaraxes'.
polar: Lines in polar coordinates (older; polarplot is preferred).
    polar(theta, rho)
quiver: Arrows for a 2-D vector field.
    quiver(x, y, u, v)
    quiver(u, v)
    quiver(..., scale)
quiver3: Arrows for a 3-D vector field.
    quiver3(x, y, z, u, v, w)

# ---- statistical plots -------------------------------------------------------------------------
boxplot: Box plots: each group's quartiles as a box with its median, whiskers out to the most extreme values within reach, and the outliers beyond.
    boxplot(X)
    boxplot(x, group)
    boxplot(..., 'Notch', 'on', 'Labels', labels, 'Orientation', 'horizontal', 'Whisker', w, 'Symbol', 'r+')
    boxplot(..., 'Widths', w, 'Colors', c, 'Positions', p, 'GroupOrder', names, 'Jitter', j, 'OutlierSize', s)
    boxplot(..., 'PlotStyle', 'compact', 'BoxStyle', 'filled', 'MedianStyle', 'target', 'LabelOrientation', 'inline')
    h = boxplot(...)
    * The groups are the columns of X, or the values of x by group (a cell of grouping variables groups by all of them at once). Values more than w (1.5) times the box's height beyond it are outliers. A notch marks an interval for the median, 1.57 IQR/sqrt(n) each way: two medians whose notches do not overlap differ at about the 5% level.
    * h has a column of seven lines for each box, with the Tags 'Upper Whisker', 'Lower Whisker', 'Upper Adjacent Value', 'Lower Adjacent Value', 'Box', 'Median' and 'Outliers'.
gscatter: A scatter plot by group: each group in its own color and marker, named in a legend.
    gscatter(x, y, group)
    gscatter(x, y, group, colors, markers, sizes)
    gscatter(x, y, group, colors, markers, sizes, 'off', xname, yname)
    h = gscatter(...)
    * colors is a string of color letters ('rgb'), an m-by-3 matrix or a cell of color names, markers a string of marker symbols ('o+x'); each is used in turn, one for each group. 'off' leaves out the legend. h has a line for each group.
gplotmatrix: A matrix of scatter plots by group: the columns of Y against those of X, or those of X against each other.
    gplotmatrix(X, [], group)
    gplotmatrix(X, Y, group)
    gplotmatrix(X, Y, group, colors, markers, sizes, legend, dispopt, xnames, ynames)
    [h, ax, bigax] = gplotmatrix(...)
    * With Y empty the diagonal shows each variable by dispopt: 'stairs' (an outlined histogram for each group, the default), 'hist' (one histogram), 'grpbars' (the groups' bars side by side), 'variable' (its name) or 'none'. Only the outer plots have tick labels. bigax, invisible axes over the whole matrix, is made the current axes, so that title and the like label the whole.
plotmatrix: A matrix of scatter plots: the columns of Y against those of X, or those of X against each other with histograms on the diagonal.
    plotmatrix(X)
    plotmatrix(X, Y)
    plotmatrix(..., linespec)
    [S, AX, BigAx, H, HAx] = plotmatrix(...)
scatterhist: A scatter plot with the histograms of x and y beside it.
    scatterhist(x, y)
    scatterhist(x, y, 'Group', g, 'Kernel', 'on' | 'overlay', 'NBins', [nx ny], 'Location', 'SouthWest' | 'SouthEast' | 'NorthWest' | 'NorthEast', 'Direction', 'in' | 'out')
    scatterhist(..., 'Color', c, 'Marker', m, 'MarkerSize', s, 'LineStyle', ls, 'LineWidth', w, 'Style', 'stairs' | 'bar', 'Bandwidth', bw, 'Legend', 'off', 'PlotGroup', 'off')
    h = scatterhist(...)
    * The histograms sit below and to the left of the scatter plot unless Location says otherwise, their bars pointing toward it ('Direction', 'in'). By group, each group has its own color and its own outlined histogram, or with 'Kernel' its density curve. h has the three axes: the scatter plot's, x's histogram's and y's.
histfit: A histogram of data with a fitted density drawn over it.
    histfit(x)
    histfit(x, nbins)
    histfit(x, nbins, dist)
    h = histfit(...)
    * The density is scaled to the histogram's counts. dist is a name fitdist knows ('normal' unless given, 'lognormal', 'gamma', 'weibull', 'kernel', 'poisson', ...); a discrete distribution has a bar for each whole number. nbins is the square root of the number of values, rounded up, unless given. h has the bars and the line.
normplot: A normal probability plot: the sorted data against normal quantiles, on an axis marked in probabilities.
    normplot(x)
    h = normplot(X)
    * Normal data lie near the straight line through the quartiles (solid between them, dashed beyond). A matrix gives points for each column. h has the points' lines, then the solid lines, then the dashed ones.
qqplot: A quantile-quantile plot: a sample's quantiles against those of the standard normal, of a distribution, or of another sample.
    qqplot(x)
    qqplot(x, pd)
    qqplot(x, y)
    qqplot(x, y, pvec)
    h = qqplot(...)
    * Points near the line through the quartiles mean that the two distributions differ at most in location and scale. For samples of two sizes the larger one's quantiles are taken at the smaller one's plotting positions; pvec gives percentiles to plot instead.
cdfplot: The empirical distribution function of a sample, drawn as steps.
    cdfplot(x)
    [h, stats] = cdfplot(x)
    * stats has the sample's min, max, mean, median and std.
lsline: Least-squares lines through the scatter plots in the current axes.
    lsline
    h = lsline(ax)
    * A line is fitted to each plot of points alone (markers without lines) and drawn across its x values, in its color.
refline: A reference line y = m*x + b across the current axes.
    refline(m, b)
    refline([m b])
    h = refline(...)
    * With no inputs, the least-squares lines of lsline.
refcurve: A polynomial curve across the current axes.
    refcurve(p)
    h = refcurve(p)
    * p has the coefficients from the highest power down, as polyval takes them.

# ---- surfaces, contours and images ------------------------------------------------------------
contour: Contour lines of a matrix.
    contour(Z)
    contour(X, Y, Z)
    contour(..., n)
    contour(..., levels)
    [C, h] = contour(...)
contourf: Filled contours.
    contourf(Z)
    contourf(X, Y, Z, n)
contour3: Contour lines drawn at their heights in 3-D.
    contour3(X, Y, Z, n)
contourc: The contour matrix, without drawing.
    C = contourc(Z)
    C = contourc(x, y, Z, n)
clabel: Label contour lines with their values.
    clabel(C, h)
fcontour: Contours of a function of two variables.
    fcontour(f)
    fcontour(f, [xmin xmax ymin ymax])
ezcontour: Contours of a function of two variables (older; fcontour is preferred).
    ezcontour(f)
surf: A surface of coloured faces.
    surf(Z)
    surf(X, Y, Z)
    surf(X, Y, Z, C)
    h = surf(..., 'Name', value)
surfc: A surface with contours under it.
    surfc(X, Y, Z)
surfl: A surface lit from a light.
    surfl(X, Y, Z)
mesh: A wire-frame surface.
    mesh(Z)
    mesh(X, Y, Z)
meshc: A mesh with contours under it.
    meshc(X, Y, Z)
meshz: A mesh with a curtain round its edges.
    meshz(X, Y, Z)
waterfall: A mesh drawn as a row of curtains.
    waterfall(X, Y, Z)
pcolor: A pseudocolour plot: a flat surface coloured by value.
    pcolor(C)
    pcolor(X, Y, C)
surface: Add a surface to the current axes, without clearing them.
    surface(X, Y, Z)
    h = surface(..., 'Name', value)
fsurf: A surface of a function of two variables.
    fsurf(f)
    fsurf(f, [xmin xmax ymin ymax])
fmesh: A mesh of a function of two variables.
    fmesh(f)
ezsurf: A surface of a function of two variables (older; fsurf is preferred).
    ezsurf(f)
ezmesh: A mesh of a function of two variables (older; fmesh is preferred).
    ezmesh(f)
image: Show an image: a matrix of colour indices, or an m-by-n-by-3 array of colours.
    image(C)
    image(x, y, C)
imagesc: Show a matrix as an image, its values scaled to the colormap.
    imagesc(C)
    imagesc(x, y, C)
    imagesc(..., clims)
imshow: Show an image, with equal axes and no ticks.
    imshow(I)
    imshow(I, [low high])
peaks: A sample function of two variables with peaks and valleys.
    Z = peaks
    Z = peaks(n)
    [X, Y, Z] = peaks(n)
sphere: The coordinates of a unit sphere, or draw one.
    [X, Y, Z] = sphere
    [X, Y, Z] = sphere(n)
    sphere(n)
cylinder: The coordinates of a cylinder with a given radius profile, or draw one.
    [X, Y, Z] = cylinder
    [X, Y, Z] = cylinder(r, n)
ellipsoid: The coordinates of an ellipsoid, or draw one.
    [X, Y, Z] = ellipsoid(xc, yc, zc, xr, yr, zr)
    [X, Y, Z] = ellipsoid(..., n)
shading: How surfaces are coloured: flat, interp (smooth) or faceted (with edges).
    shading flat | interp | faceted
view: The viewpoint: azimuth and elevation in degrees.
    view(2)
    view(3)
    view(az, el)
    [az, el] = view
    view(tree)
    * view(tree) of a classification or regression tree prints its rules, node by node.
camzoom: Zoom the camera: the axes drawn larger by a factor above 1, smaller by one below.
    camzoom(f)
    camzoom(ax, f)
    * It narrows the axes' CameraViewAngle by the factor; the axes may then reach past their Position, as far as their figure or panel.
camva: The camera's view angle in degrees: a smaller angle draws the axes larger.
    va = camva
    camva(va)
    camva(ax, va)
    m = camva('mode')
    camva auto | manual
    * The axes' CameraViewAngle. Left automatic it is 6.6086 for a view from above (10.3396 in 3-D), and the axes fill their place.
light: Add a light to the axes.
    light
    h = light('Position', [x y z])
camlight: Add a light near the camera.
    camlight
    camlight headlight | right | left
lighting: How lit surfaces are shaded.
    lighting flat | gouraud | none
material: Accepted, with no effect.
    material shiny | dull | metal | default
colorbar: Show the colour scale beside the axes.
    colorbar
    colorbar off
    colorbar(location)
    c = colorbar
colormap: Set or get the colours of the figure's colour scale.
    colormap(name)
    colormap(map)
    map = colormap
    colormap(name, n)
clim: The limits of the colour scale.
    clim([cmin cmax])
    lims = clim
    clim auto
caxis: The limits of the colour scale (older name of clim).
    caxis([cmin cmax])
    lims = caxis
alpha: Accepted, with no effect: transparency is set by FaceAlpha on the object.
    alpha(value)
hidden: Accepted, with no effect.
    hidden on | off

# ---- figures and axes ------------------------------------------------------------------------
figure: Make a new figure window, or bring one to the front and make it current.
    figure
    figure(n)
    f = figure('Name', value, ...)
clf: Clear the current figure.
    clf
    clf reset
close: Close figures.
    close
    close(n)
    close all
    close(v)
    * close(v) closes a VideoWriter's file (open(v) opens it).
gcf: The current figure (one is made when there is none).
    f = gcf
gca: The current axes (made when there are none).
    ax = gca
gco: The object last clicked in a figure.
    h = gco
groot: The graphics root object; its properties hold the defaults.
    r = groot
axes: Make axes in the current figure, or make some axes current.
    ax = axes
    ax = axes('Position', [left bottom width height])
    axes(ax)
cla: Clear the current axes.
    cla
    cla(ax)
subplot: Axes in a grid of tiles within the figure.
    subplot(m, n, p)
    subplot(m, n, [p1 p2])
    subplot(m, n, p, ax)
    subplot(ax)
    ax = subplot(...)
    * With ax after p, those axes (polaraxes, for one) take the tile; axes overlapping it are deleted. subplot(ax) makes ax the current axes.
tiledlayout: A grid of tiles for axes.
    tiledlayout(m, n)
    tiledlayout('flow')
nexttile: Axes in the next tile of a tiledlayout.
    nexttile
    nexttile(k)
    ax = nexttile
hold: Keep what is drawn when the next plot is added, or not.
    hold on
    hold off
    hold
ishold: True when hold is on.
    tf = ishold
newplot: Prepare the axes for a new plot as the plotting functions do (clear them unless hold is on).
    ax = newplot
axis: Set the axis limits and how the axes are shaped.
    axis([xmin xmax ymin ymax])
    axis([xmin xmax ymin ymax zmin zmax])
    axis equal | tight | square | normal | ij | xy | auto | off | on
    lims = axis
xlim: The limits of the x axis.
    xlim([xmin xmax])
    lims = xlim
    xlim auto
ylim: The limits of the y axis.
    ylim([ymin ymax])
    lims = ylim
zlim: The limits of the z axis.
    zlim([zmin zmax])
    lims = zlim
xticks: The positions of the ticks on the x axis.
    xticks(ticks)
    t = xticks
yticks: The positions of the ticks on the y axis.
    yticks(ticks)
zticks: The positions of the ticks on the z axis.
    zticks(ticks)
xticklabels: The labels of the ticks on the x axis.
    xticklabels(labels)
yticklabels: The labels of the ticks on the y axis.
    yticklabels(labels)
zticklabels: The labels of the ticks on the z axis.
    zticklabels(labels)
xtickangle: Turn the labels of the x ticks.
    xtickangle(angle)
    angle = xtickangle
ytickangle: Turn the labels of the y ticks.
    ytickangle(angle)
    angle = ytickangle
grid: Show or hide the grid lines.
    grid on | off | minor
    grid
box: Show or hide the box round the axes.
    box on | off
daspect: The data aspect ratio: how long one unit is on each axis.
    daspect([1 1 1])
    r = daspect
    daspect('auto')
    m = daspect('mode')
pbaspect: The plot box aspect ratio.
    pbaspect([1 1 1])
    r = pbaspect
    pbaspect('auto')
    m = pbaspect('mode')
yyaxis: Axes with a second y axis on the right; pick which side the next plot uses.
    yyaxis left
    yyaxis right
colororder: The colours the lines take in turn.
    colororder(colors)
    c = colororder
title: The title of the axes.
    title(text)
    title(text, 'Name', value)
    t = title(...)
    * Text is drawn with a small TeX subset: ^{} and _{} for super- and subscripts, \alpha and the other Greek letters, \pm, \circ, \infty.
subtitle: A subtitle under the title of the axes.
    subtitle(text)
sgtitle: A title over a grid of subplots.
    sgtitle(text)
suptitle: A title over a grid of subplots (older; sgtitle is preferred).
    suptitle(text)
xlabel: The label of the x axis.
    xlabel(text)
ylabel: The label of the y axis.
    ylabel(text)
zlabel: The label of the z axis.
    zlabel(text)
legend: A legend of the plotted objects.
    legend
    legend(label1, label2, ...)
    legend(labels)
    legend(..., 'Location', 'northeast' | 'best' | ...)
    legend off
    legend show
text: Text at a point of the axes.
    text(x, y, s)
    text(x, y, z, s)
    h = text(..., 'Name', value)
annotation: A line, an arrow, a text arrow, a rectangle, an ellipse or a text box on the figure, in normalized figure units.
    h = annotation('line', [x1 x2], [y1 y2])
    h = annotation('arrow', [x1 x2], [y1 y2])
    h = annotation('doublearrow', [x1 x2], [y1 y2])
    h = annotation('textarrow', [x1 x2], [y1 y2], 'String', s)
    h = annotation('rectangle', [x y w h])
    h = annotation('ellipse', [x y w h])
    h = annotation('textbox', [x y w h], 'String', s)
    h = annotation(fig, ...)
    * (0, 0) is the figure's lower left corner and (1, 1) its upper right. An arrow's head is at its second point; a text arrow's text is at its first, on the side away from the head.
    * Their properties: X and Y (the ends) or Position, Color, LineStyle and LineWidth; HeadStyle ('vback2', 'plain', 'diamond', 'ellipse', 'rectangle', 'none' ...), HeadLength and HeadWidth in points (Head1... and Head2... for the two heads of a double arrow); FaceColor and FaceAlpha for a rectangle or an ellipse; String, FontSize and the font, Color (of the text), BackgroundColor, EdgeColor, Margin and FitBoxToText for a text box; TextColor, TextBackgroundColor and TextEdgeColor for a text arrow.
    * Annotations are not among the figure's Children: findobj and findall find them by Type ('lineshape', 'arrowshape', 'doubleendarrowshape', 'textarrowshape', 'rectangleshape', 'ellipseshape', 'textboxshape').
set: Set properties of graphics objects.
    set(h, 'Name', value, ...)
    set(h, s)
get: Properties of graphics objects.
    v = get(h, 'Name')
    s = get(h)
findobj: Graphics objects with given properties.
    h = findobj
    h = findobj('Type', 'line')
    h = findobj(parent, 'Name', value, ...)
    h = findobj(parent, 'Tag', 'a', '-or', 'Tag', 'b')
    h = findobj(parent, '-regexp', 'Tag', '^row', '-not', 'Type', 'text')
    h = findobj(parent, '-depth', 1, ...)
    * With no parent it looks from the root (0), which it finds too; the parents given are found if they pass.
    * The tests: a property and its value; -regexp, a property and a pattern; -property and a name (objects that have it); -function and a function handle, given the object, or given a property's value when the property's name comes first.
    * Tests next to each other must all pass (-and); -or and -xor join the tests on either side, from left to right; -not turns the next test round.
    * flat looks at the parents only, -depth d that many levels down.
    * It leaves out objects whose HandleVisibility is 'off', and 'callback' ones (dialogs) unless a callback is running; findall, or set(0, 'ShowHiddenHandles', 'on'), finds them all.
findall: Graphics objects with given properties, hidden ones included.
    h = findall(parent, 'Name', value, ...)
    * It takes what findobj takes.
allchild: Every child of a graphics object.
    h = allchild(parent)
ancestor: The ancestor of a graphics object of a given type.
    p = ancestor(h, 'figure' | 'axes')
copyobj: Copies of graphics objects, each with everything under it, in a new parent.
    c = copyobj(h, parent)
    c = copyobj([ax lgd], fig)
    * h may be several objects, with one parent or one for each. A legend or colorbar is copied together with its axes, and the copy then belongs to the axes' copy. A figure itself is not copied.
gobjects: An array of empty graphics placeholders.
    h = gobjects(n)
ishandle: True for valid graphics handles.
    tf = ishandle(h)
isgraphics: True for valid graphics objects (of a type, if given).
    tf = isgraphics(h)
    tf = isgraphics(h, type)
isvalid: True for objects that have not been deleted.
    tf = isvalid(h)
ishghandle: True for valid graphics handles.
    tf = ishghandle(h)
isprop: True when an object has a property.
    tf = isprop(h, name)
drawnow: Draw the figures now (while a long program runs), and run the callbacks of what people did meanwhile.
    drawnow
    drawnow limitrate
    drawnow nocallbacks
    * pause, uiwait and waitfor run waiting callbacks too.
refresh: Accepted, with no effect: figures redraw by themselves.
    refresh
shg: Accepted, with no effect.
    shg
getframe: The figure or axes as drawn, as a movie frame.
    F = getframe
    F = getframe(ax)
    F = getframe(fig)
    F = getframe(h, [left bottom width height])
    * F.cdata is the picture, rows by columns by 3 of uint8, as large as the figure is on screen in pixels; F.colormap is [].
    * With no input it takes the current axes (the figure when there are none). An axes' frame is its box as drawn, without the tick labels outside it; a rectangle is in pixels from the lower left corner of the figure or axes.
    * frame2im(F) gives the picture, movie(F) plays a struct array of frames, and im2frame makes a frame of a picture.
frame2im: The picture of a movie frame.
    X = frame2im(F)
    [X, map] = frame2im(F)
    * X is F.cdata (rows by columns by 3 of uint8 from getframe) and map is F.colormap.
im2frame: A movie frame of a picture.
    F = im2frame(X)
    F = im2frame(X, map)
    * X is rows by columns by 3 (doubles from 0 to 1 become uint8), or a matrix of colormap indices with its colormap.
movie: Play a movie's frames in the current axes.
    movie(F)
    movie(F, n)
    movie(F, n, fps)
    movie(h, F, ...)
    * F is a struct array of frames (getframe's or im2frame's). n plays them n times (back and forth for a negative n); n = [k i j ...] plays the frames i, j, ... k times. fps frames a second, 12 unless given.
saveas: Save a figure as a picture or vector file, by the extension, or as a figure file (.fig).
    saveas(fig, filename)
    saveas(fig, filename, format)
    saveas(fig, 'plot.fig')
    * The files: .png and .jpg pictures at twice the figure's size on screen, .bmp and .tif (uncompressed), and .svg, .pdf and .eps, which keep lines and text as lines and text. format ('png', 'jpeg', 'bmp', 'tiff', 'svg', 'pdf', 'epsc') gives the kind when the name has no extension.
    * PDF and EPS write text in the standard fonts, Helvetica or Courier with Greek letters and mathematical signs from Symbol; other characters come out as ?, while SVG keeps all text. EPS has no transparency: translucent colours are mixed with white.
    * The figure's own controls (uicontrol and the like) are not in the file.
exportgraphics: Save a figure as a picture or vector file.
    exportgraphics(obj, filename)
    exportgraphics(obj, filename, 'Resolution', dpi)
    * The extension decides the kind, as for saveas: .png, .jpg, .bmp, .tif, .svg, .pdf or .eps. Given an axes, the whole figure it is in is written.
openfig: Open a figure saved in a figure file (.fig).
    openfig(filename)
    h = openfig(filename, 'new' | 'reuse')
    h = openfig(filename, 'visible' | 'invisible')
    * A .fig file is a MAT-file holding the figure as a tree of structs (hgS_070000). Axes, lines, surfaces, patches, images, text, lights, figure controls and menus are made again, with their callbacks (as text); a CreateFcn runs when all are made.
    * Groups of older releases (hggroup, lineseries, scatter groups) come as what they draw; objects of other kinds are left out with a warning.
    * Files saved with savefig's 'compact' keep the figure only in the form of R2014b and later, which is not read.
    * 'reuse' brings forward the figure opened from the same file, if there is one.
hgload: Open the objects saved in a figure file.
    h = hgload(filename)
    h = hgload(filename, props)
    * props is a struct of properties set on what is opened.
savefig: Save figures as a figure file (.fig), to open again with openfig.
    savefig(filename)
    savefig(fig, filename)
    * fig may be several figures; the file holds them all. 'compact' is accepted and writes the usual form.
    * Callbacks given as function handles are left out, with a warning: text callbacks are kept. Annotations are left out too, with a warning.
hgsave: Save a figure (or other graphics objects) as a figure file.
    hgsave(filename)
    hgsave(h, filename)
print: Save the current figure as a picture or vector file.
    print(filename, '-dpng')
    print(fig, filename, '-dpdf')
    print(filename, '-dpng', '-r300')
    * The devices are -dpng, -djpeg, -dbmp, -dtiff, -dsvg, -dpdf and -depsc (or -deps); the file's extension decides when it has a known one, and PNG when there is neither. -r gives a picture's resolution in dots an inch (screen pixels are 96 an inch; 192 unless given).
    * print -dmeta with no file name copies the figure to the clipboard.
ginput: Points clicked in the current figure.
    [x, y] = ginput(n)
    [x, y, button] = ginput(n)
    * Enter (or Escape) ends early.
waitforbuttonpress: Wait for a click in a figure or a key press.
    waitforbuttonpress
zoom: Accepted, with no effect: use the figure window's zoom tool, or scroll.
    zoom on | off
pan: Accepted, with no effect: drag in the figure window to pan.
    pan on | off
rotate3d: Accepted, with no effect: drag in a 3-D view to turn it.
    rotate3d on | off
datacursormode: Accepted, with no effect: use the figure window's data tip tool.
    datacursormode on | off
brush: Accepted, with no effect.
    brush on | off
linkaxes: Accepted, with no effect.
    linkaxes(ax)
linkprop: Accepted, with no effect.
    linkprop(h, props)
uistack: Bring an object to the front of its siblings, or send it back.
    uistack(h, 'top')
    uistack(h, 'up' | 'down', steps)
    uistack(h, 'bottom')
inspect: Open the property editor beside a figure, showing a graphics object's properties.
    inspect(h)
    inspect
    * With no input it shows the current figure. Each property has a field that suits it (a colour, on or off, a list of choices, numbers, text); a change is set as set(h, name, value) sets it.
    * The editor lists the figure's objects as a tree (axes with their title and labels, what is plotted, legend, colorbar, annotations, controls): click one to show its properties.
plotedit: Turn a figure's edit mode on or off: a click in the figure then picks a part of it for the property editor.
    plotedit on | off
    plotedit
    plotedit(fig, 'on' | 'off')
    * With no option it switches the mode. In edit mode a click reaches neither the program's callbacks nor its controls.
    * The figure toolbar's arrow button does the same.
movegui: Move a figure window: to the middle of the desktop, or to an edge.
    movegui(fig, 'center')
    movegui(fig, 'north' | 'south' | 'east' | 'west' | 'northeast' | ...)
whitebg: Accepted, with no effect.
    whitebg

# ---- user interfaces -------------------------------------------------------------------------
uicontrol: A control in a figure: a button, check box, text field, slider, list and more.
    h = uicontrol('Style', 'pushbutton', 'String', 'Go', 'Callback', @go)
    h = uicontrol(parent, 'Name', value, ...)
    uicontrol(h)
    * Style: pushbutton, togglebutton, checkbox, radiobutton, edit, text, slider, listbox, popupmenu or frame.
    * Position [left bottom width height] is in Units (pixels unless set) from the lower left of the parent.
    * Value is the state (Max when on, Min when off), the slider's place, or the chosen items of a list (1-based).
    * Callback runs when the control is used: text (run in the base workspace), a function handle called as f(src, event), or a cell {f, a, b} called as f(src, event, a, b).
    * uicontrol(h) gives h the keyboard.
uipanel: A panel in a figure: a frame with a title that holds controls and axes.
    p = uipanel('Title', 'Settings', 'Position', [0.05 0.05 0.4 0.9])
    p = uipanel(parent, 'Name', value, ...)
    * What it holds is placed from the panel's lower left, in its own Units.
uibuttongroup: A panel whose radio buttons and toggle buttons are chosen one at a time.
    g = uibuttongroup('Title', 'Method', 'SelectionChangedFcn', @changed)
    * SelectedObject is the chosen button; SelectionChangedFcn gets OldValue and NewValue in its event data.
uitable: A table of numbers, logical values or text in a figure.
    t = uitable('Data', magic(4), 'ColumnName', {'a', 'b', 'c', 'd'})
    t = uitable(parent, 'Name', value, ...)
    * ColumnEditable says which columns can be typed in; CellEditCallback gets Indices, PreviousData and NewData.
uitabgroup: A set of tabs in a figure; each tab holds controls and axes.
    g = uitabgroup(parent)
    * SelectedTab is the tab shown; SelectionChangedFcn runs when someone picks another.
uitab: A tab of a tab group.
    t = uitab(g, 'Title', 'Data')
uimenu: A menu in a figure's menu bar, an item of a menu, or an item of a context menu.
    m = uimenu(fig, 'Label', '&File')
    item = uimenu(m, 'Label', 'Open', 'Accelerator', 'O', 'Callback', @open)
    * Accelerator is a key that, with Ctrl (Command on a Mac), chooses the item.
    * Checked, Enable and Separator are 'on' or 'off'; Text and MenuSelectedFcn are other names for Label and Callback.
uicontextmenu: A menu that opens where someone right-clicks an object.
    cm = uicontextmenu(fig);
    uimenu(cm, 'Label', 'Delete', 'Callback', @remove)
    set(h, 'UIContextMenu', cm)
uitoolbar: A toolbar in a figure, for push and toggle tools.
    tb = uitoolbar(fig)
uipushtool: A button with a picture on a toolbar.
    t = uipushtool(tb, 'CData', icon, 'TooltipString', 'Open', 'ClickedCallback', @open)
    * CData is the picture: m x n x 3 colours from 0 to 1 (or uint8); NaN shows through.
uitoggletool: A toolbar button that stays in or out.
    t = uitoggletool(tb, 'CData', icon, 'OnCallback', @on, 'OffCallback', @off)
    * State is 'on' or 'off'; ClickedCallback runs after OnCallback or OffCallback.
gcbo: The object whose callback is running, and its figure.
    h = gcbo
    [h, fig] = gcbo
    * Empty outside callbacks.
gcbf: The figure of the object whose callback is running.
    fig = gcbf
closereq: Close the figure whose close button was pressed (the default CloseRequestFcn).
    closereq
uiwait: Wait (letting callbacks run) until a figure is closed or uiresume is called.
    uiwait(fig)
    uiwait(fig, seconds)
uiresume: End a uiwait.
    uiresume(fig)
waitfor: Wait (letting callbacks run) until an object is deleted or a property changes.
    waitfor(h)
    waitfor(h, 'Name')
    waitfor(h, 'Name', value)
guidata: Keep data with a figure, or get it back (from any object in the figure).
    guidata(h, data)
    data = guidata(h)
setappdata: Keep a named value with a graphics object.
    setappdata(h, 'name', value)
getappdata: A named value kept with a graphics object ([] when there is none), or all of them as a struct.
    value = getappdata(h, 'name')
    s = getappdata(h)
isappdata: True when a graphics object keeps a value of that name.
    tf = isappdata(h, 'name')
rmappdata: Forget a named value kept with a graphics object.
    rmappdata(h, 'name')
msgbox: A window with a message and an OK button; the program goes on.
    h = msgbox(message)
    h = msgbox(message, title)
    h = msgbox(message, title, 'error' | 'warn' | 'help')
    h = msgbox(message, title, 'custom', picture, colormap)
    * uiwait(h) waits until it is closed. 'modal' as the last input makes it modal: until it is closed, the rest of the page takes no clicks or keys (Ctrl+C still stops a program).
errordlg: A message window with an error sign.
    h = errordlg(message, title)
warndlg: A message window with a warning sign.
    h = warndlg(message, title)
helpdlg: A message window with an information sign.
    h = helpdlg(message, title)
questdlg: Ask a question with buttons; the answer is the text of the button pressed.
    answer = questdlg(question)
    answer = questdlg(question, title, 'Yes', 'No', 'Yes')
    answer = questdlg(question, title, b1, b2, b3, default)
    * With no buttons given they are Yes, No and Cancel; closing the window answers ''.
inputdlg: Ask for one or more lines of text.
    answers = inputdlg(prompt)
    answers = inputdlg({'Name', 'Age'}, title, [1; 1], {'Ada', '36'})
    * The answers are a cell array of text, {} when the window is cancelled.
listdlg: Ask for a choice from a list.
    [indx, tf] = listdlg('ListString', items)
    [indx, tf] = listdlg('ListString', items, 'SelectionMode', 'single', 'PromptString', text, 'Name', title)
    * tf is 0 and indx empty when the window is cancelled.
uigetfile: Ask for a file to open, among the page's files.
    [file, path] = uigetfile
    [file, path, index] = uigetfile({'*.m'; '*.mat'}, title)
    [file, path, index] = uigetfile({'*.csv', 'Data (*.csv)'}, title, 'MultiSelect', 'on')
    * file is 0 when the window is cancelled; path ends with /.
uiputfile: Ask for a name and folder to save a file in, among the page's files.
    [file, path, index] = uiputfile({'*.txt', 'Text (*.txt)'}, title, 'results.txt')
    * index is the file type chosen; a name typed without one gets that type's extension.
uigetdir: Ask for a folder, among the page's folders.
    folder = uigetdir
    folder = uigetdir(start, title)
uisetcolor: Ask for a colour.
    rgb = uisetcolor
    rgb = uisetcolor([1 0 0], title)
waitbar: A window with a bar that shows how far a long job has come.
    h = waitbar(0, 'Working...')
    waitbar(fraction, h)
    waitbar(fraction, h, 'Almost there')
    h = waitbar(0, 'Working...', 'CreateCancelBtn', 'setappdata(gcbf, ''cancelled'', 1)')
    * waitbar(fraction) alone moves the newest bar.
dialog: An empty modal window for a dialog of one's own making.
    d = dialog('Name', 'Settings', 'Position', [300 300 250 150])
    * Its WindowStyle is 'modal': until it is closed (or made 'normal'), the rest of the page takes no clicks or keys.
menu: Ask for a choice among buttons; the number of the button pressed (0 when the window is closed).
    k = menu('Shape', 'Circle', 'Square', 'Triangle')
printdlg: Print a figure, with the browser's printing.
    printdlg(fig)
printpreview: Print a figure, with the browser's printing.
    printpreview(fig)
helpwin: Show the help of a function in the Help panel.
    helpwin name
doc: Show the help of a function in the Help panel.
    doc name
timer: A timer that runs a callback after a delay, and again as often as asked.
    t = timer('TimerFcn', @tick, 'Period', 1, 'ExecutionMode', 'fixedRate')
    start(t)
    * ExecutionMode: singleShot (once, the default), fixedRate, fixedSpacing or fixedDelay.
    * TasksToExecute stops it after so many runs; BusyMode says what a tick does while the last one has not run.
    * The callbacks run when the engine is idle, or at a running program's drawnow and pause.
start: Start a timer.
    start(t)
stop: Stop a timer (or an audioplayer or audiorecorder).
    stop(t)
    stop(player)
wait: Wait (letting callbacks run) until a timer stops; for futures, until they finish.
    wait(t)
    wait(F)
timerfind: The timers there are, or those with given properties.
    t = timerfind
    t = timerfind('Name', value, ...)
timerfindall: The timers there are, hidden ones included.
    t = timerfindall

# ---- colormaps -------------------------------------------------------------------------------
parula: A colormap from blue through green to yellow (the default here).
    c = parula
    c = parula(n)
viridis: A perceptually uniform colormap from dark purple to yellow.
    c = viridis(n)
turbo: A rainbow colormap with smooth steps in lightness.
    c = turbo(n)
jet: The classic rainbow colormap, from dark blue to dark red.
    c = jet(n)
gray: A gray scale from black to white.
    c = gray(n)
hot: Black, red, yellow, white.
    c = hot(n)
cool: Cyan to magenta.
    c = cool(n)
spring: Magenta to yellow.
    c = spring(n)
summer: Green to yellow.
    c = summer(n)
autumn: Red through orange to yellow.
    c = autumn(n)
winter: Blue to green.
    c = winter(n)
bone: A gray scale with a tint of blue.
    c = bone(n)
copper: Black to a light copper.
    c = copper(n)
pink: Pastel shades of pink.
    c = pink(n)
hsv: The hues of the colour circle, red to red.
    c = hsv(n)
lines: The colours of the line color order, repeated.
    c = lines(n)
prism: Red, orange, yellow, green, blue and violet, repeated.
    c = prism(n)
flag: Red, white, blue and black, repeated.
    c = flag(n)
white: All white.
    c = white(n)
colorcube: A colormap of evenly spaced colours of a colour cube, then grays and pure tones.
    c = colorcube(n)
# ---- arguments: validators and inputParser ---------------------------------------------------
mustBePositive: An error unless every element is greater than 0.
    mustBePositive(A)
mustBeNonnegative: An error unless every element is 0 or more.
    mustBeNonnegative(A)
mustBeNegative: An error unless every element is less than 0.
    mustBeNegative(A)
mustBeNonpositive: An error unless every element is 0 or less.
    mustBeNonpositive(A)
mustBeNonzero: An error if any element is 0.
    mustBeNonzero(A)
mustBeInteger: An error unless every element is a whole number (finite).
    mustBeInteger(A)
mustBeNumeric: An error unless the value is numeric.
    mustBeNumeric(A)
mustBeNumericOrLogical: An error unless the value is numeric or logical.
    mustBeNumericOrLogical(A)
mustBeFloat: An error unless the value is single or double.
    mustBeFloat(A)
mustBeReal: An error if any element has an imaginary part.
    mustBeReal(A)
mustBeFinite: An error if any element is Inf or NaN.
    mustBeFinite(A)
mustBeNonNan: An error if any element is NaN.
    mustBeNonNan(A)
mustBeNonempty: An error if the value is empty.
    mustBeNonempty(A)
mustBeNonsparse: An error if the value is sparse.
    mustBeNonsparse(A)
mustBeGreaterThan: An error unless every element is greater than a number.
    mustBeGreaterThan(A, c)
mustBeGreaterThanOrEqual: An error unless every element is at least a number.
    mustBeGreaterThanOrEqual(A, c)
mustBeLessThan: An error unless every element is less than a number.
    mustBeLessThan(A, c)
mustBeLessThanOrEqual: An error unless every element is at most a number.
    mustBeLessThanOrEqual(A, c)
mustBeInRange: An error unless every element lies within two bounds.
    mustBeInRange(A, lower, upper)
    mustBeInRange(A, lower, upper, 'exclusive')
    * The bounds are included unless 'exclusive', 'exclude-lower' or 'exclude-upper' says otherwise.
mustBeMember: An error unless every element is one of a set of values (or texts).
    mustBeMember(A, S)
mustBeText: An error unless the value is a character vector, a string array or a cell of character vectors.
    mustBeText(A)
mustBeTextScalar: An error unless the value is a character vector or a string scalar.
    mustBeTextScalar(A)
mustBeNonzeroLengthText: An error unless the value is text with at least one character in each element.
    mustBeNonzeroLengthText(A)
mustBeVector: An error unless the value is a row or a column.
    mustBeVector(A)
    mustBeVector(A, 'allow-all-empties')
mustBeScalarOrEmpty: An error unless the value has at most one element.
    mustBeScalarOrEmpty(A)
mustBeA: An error unless the value is of one of the classes named ('numeric', 'float' and 'integer' name groups).
    mustBeA(A, classNames)
mustBeUnderlyingType: An error unless the value's class is one of those named.
    mustBeUnderlyingType(A, typeNames)
mustBeNonmissing: An error if any element is missing (NaN, or a missing string).
    mustBeNonmissing(A)
mustBeValidVariableName: An error unless the text is a valid variable name.
    mustBeValidVariableName(name)
mustBeFile: An error unless each name is a file that exists.
    mustBeFile(path)
mustBeFolder: An error unless each name is a folder that exists.
    mustBeFolder(path)
inputParser: An object that checks a function's inputs and gives their values by name.
    p = inputParser
    addRequired(p, name, validationFcn)
    addOptional(p, name, default, validationFcn)
    addParameter(p, name, default, validationFcn)
    parse(p, varargin{:})
    p.Results
    * Properties: FunctionName, CaseSensitive (false), KeepUnmatched (false), PartialMatching (true), StructExpand (true); after parse, Results, Unmatched, UsingDefaults and Parameters.
    * A validation function returns true or false, or gives an error for a bad value.
addRequired: Add a required input to an inputParser.
    addRequired(p, name)
    addRequired(p, name, validationFcn)
    p.addRequired(name, validationFcn)
addOptional: Add an optional positional input, with its default, to an inputParser.
    addOptional(p, name, default)
    addOptional(p, name, default, validationFcn)
    * Text that names a parameter ends the optional inputs.
addParameter: Add a name-value input, with its default, to an inputParser.
    addParameter(p, name, default)
    addParameter(p, name, default, validationFcn)
    addParameter(..., 'PartialMatchPriority', n)
addParamValue: The older name of addParameter.
    addParamValue(p, name, default, validationFcn)
parse: Parse a list of inputs with an inputParser, filling its Results.
    parse(p, varargin{:})
    p.parse(varargin{:})
nargchk: The message for a number of inputs outside a range (the older form of narginchk).
    msg = nargchk(low, high, n)
    s = nargchk(low, high, n, 'struct')
namelengthmax: The longest a name may be: 63.
    n = namelengthmax
# ---- data cleaning and grouping ---------------------------------------------------------------
fillmissing: Fill the missing entries (NaN, empty text, NaT, undefined) of data.
    F = fillmissing(A, 'constant', v)
    F = fillmissing(A, 'linear')
    F = fillmissing(A, 'movmean', window)
    F = fillmissing(..., dim, 'EndValues', 'nearest', 'MaxGap', g)
    F = fillmissing(T, method, ..., 'DataVariables', vars)
    [F, TF] = fillmissing(...)
    * Datetimes and durations fill by every method; categorical arrays by 'constant' (a category's name), 'previous', 'next' and 'nearest'. A table is filled variable by variable ('constant' may give a cell of values, one per variable).
    * Methods: 'constant', 'previous', 'next', 'nearest', 'linear', 'spline', 'pchip', 'makima', 'movmean', 'movmedian'.
    * EndValues: 'extrap' (the default), 'previous', 'next', 'nearest', 'none' or a value.
rmmissing: Remove missing entries, or the rows or columns that have them.
    R = rmmissing(A)
    R = rmmissing(A, dim)
    R = rmmissing(..., 'MinNumMissing', n)
    R = rmmissing(T, 'DataVariables', vars)
    [R, TF] = rmmissing(...)
    * A table loses the rows with a missing element in its variables (or in vars).
standardizeMissing: Make given values the standard missing value (NaN, empty text, NaT, undefined).
    B = standardizeMissing(A, indicators)
    B = standardizeMissing(T, indicators, 'DataVariables', vars)
    * For a categorical array the indicators are category names; for a table each variable takes the indicators of its kind.
missing: The missing value: it becomes NaN, <missing>, NaT or undefined where it is put.
    m = missing
    * [1 missing 3] is [1 NaN 3], ["a" missing] a string array with a missing string, d(2) = missing makes a datetime NaT and c(2) = missing a category undefined. string(missing), double(missing), datetime(missing) and categorical(missing) convert it; in arithmetic it is NaN.
isoutlier: Find outliers in data.
    TF = isoutlier(A)
    TF = isoutlier(A, method)
    TF = isoutlier(A, 'movmedian', window)
    TF = isoutlier(..., dim, 'ThresholdFactor', t)
    [TF, L, U, C] = isoutlier(...)
    * Methods: 'median' (the default: more than 3 scaled median absolute deviations away), 'mean' (3 standard deviations), 'quartiles' (1.5 interquartile ranges beyond the quartiles), 'grubbs', 'gesd', 'movmedian', 'movmean'.
filloutliers: Replace outliers in data.
    B = filloutliers(A, fillmethod)
    B = filloutliers(A, fillmethod, findmethod)
    [B, TF, L, U, C] = filloutliers(...)
    * Fill methods: 'center', 'clip', 'previous', 'next', 'nearest', 'linear', 'spline', 'pchip', 'makima', or a number.
smoothdata: Smooth noisy data.
    B = smoothdata(A)
    B = smoothdata(A, method, window)
    B = smoothdata(A, dim, method, window)
    [B, window] = smoothdata(...)
    * Methods: 'movmean' (the default), 'movmedian', 'gaussian', 'lowess', 'loess', 'rlowess', 'rloess', 'sgolay' ('Degree', 2).
findgroups: Number the groups of a grouping variable (or of several together).
    G = findgroups(A)
    [G, ID] = findgroups(A)
    [G, ID1, ID2] = findgroups(A1, A2)
splitapply: Apply a function to each group of data.
    Y = splitapply(func, X, G)
    [Y1, Y2] = splitapply(func, X1, X2, G)
    * Each call must give one row (a scalar, or a value in a cell).
histcounts2: Counts of pairs in a grid of bins.
    N = histcounts2(X, Y)
    N = histcounts2(X, Y, nbins)
    N = histcounts2(X, Y, Xedges, Yedges)
    [N, Xedges, Yedges, binX, binY] = histcounts2(...)
rms: The root mean square.
    y = rms(x)
    y = rms(x, dim)
    y = rms(x, 'all')
    y = rms(..., 'omitnan')
# ---- arrays, cells and coordinates --------------------------------------------------------------
bsxfun: Apply a two-input function with singleton dimensions expanded.
    C = bsxfun(fun, A, B)
repelem: Repeat each element of an array.
    u = repelem(v, n)
    B = repelem(A, r1, r2)
mat2cell: Divide an array into a cell array of blocks.
    C = mat2cell(A, rowSizes, colSizes)
    C = mat2cell(A, rowSizes)
celldisp: Show each element of a cell array, with its index.
    celldisp(C)
    celldisp(C, name)
swapbytes: Reverse the bytes of each element.
    Y = swapbytes(X)
spfun: Apply a function to the nonzero elements of a matrix.
    S = spfun(fun, A)
cart2pol: Cartesian to polar (or cylindrical) coordinates.
    [theta, rho] = cart2pol(x, y)
    [theta, rho, z] = cart2pol(x, y, z)
pol2cart: Polar (or cylindrical) to Cartesian coordinates.
    [x, y] = pol2cart(theta, rho)
    [x, y, z] = pol2cart(theta, rho, z)
cart2sph: Cartesian to spherical coordinates.
    [azimuth, elevation, r] = cart2sph(x, y, z)
sph2cart: Spherical to Cartesian coordinates.
    [x, y, z] = sph2cart(azimuth, elevation, r)
# ---- text and JSON ----------------------------------------------------------------------------------
replaceBetween: Replace the text between two markers or positions.
    s = replaceBetween(str, startText, endText, newText)
    s = replaceBetween(str, startPos, endPos, newText)
    s = replaceBetween(..., 'Boundaries', 'inclusive')
eraseBetween: Remove the text between two markers or positions.
    s = eraseBetween(str, startText, endText)
    s = eraseBetween(str, startPos, endPos)
matlab.lang.makeUniqueStrings: Make names unique by adding _1, _2, ...
    U = matlab.lang.makeUniqueStrings(S)
    U = matlab.lang.makeUniqueStrings(S, exclude)
    U = matlab.lang.makeUniqueStrings(S, exclude, maxLength)
jsondecode: Read JSON text into structs, arrays and cells.
    value = jsondecode(text)
jsonencode: Write a value as JSON text.
    text = jsonencode(value)
    text = jsonencode(value, 'PrettyPrint', true)
    text = jsonencode(value, 'ConvertInfAndNaN', false)
# ---- linear algebra: structure, iterative solvers, updates ------------------------------------------
issymmetric: True when a matrix equals its transpose (or minus it, with 'skew').
    tf = issymmetric(A)
    tf = issymmetric(A, 'skew')
    tf = issymmetric(A, tol)
ishermitian: True when a matrix equals its conjugate transpose (or minus it, with 'skew').
    tf = ishermitian(A)
    tf = ishermitian(A, 'skew')
    tf = ishermitian(A, tol)
istril: True for a lower triangular matrix.
    tf = istril(A)
istriu: True for an upper triangular matrix.
    tf = istriu(A)
isbanded: True when the nonzeros lie within given numbers of diagonals below and above the main one.
    tf = isbanded(A, lower, upper)
bandwidth: How far the nonzeros of a matrix reach below and above its diagonal.
    [lower, upper] = bandwidth(A)
    b = bandwidth(A, 'lower')
    fb = bandwidth(sys)
    fb = bandwidth(sys, dbdrop)
    * Of a model: the first frequency where the gain falls 3 dB (or dbdrop) below its DC gain.
pcg: Solve A*x = b by preconditioned conjugate gradients (A symmetric positive definite).
    x = pcg(A, b)
    x = pcg(A, b, tol, maxit, M1, M2, x0)
    [x, flag, relres, iter, resvec] = pcg(...)
    * A may be a function handle returning A*x; M1 and M2 too, returning M\x. flag 0 is converged, 1 the iterations ran out.
bicg: Solve A*x = b by biconjugate gradients.
    [x, flag, relres, iter, resvec] = bicg(A, b, tol, maxit, M1, M2, x0)
    * A function handle is called as afun(x, 'notransp') and afun(x, 'transp').
bicgstab: Solve A*x = b by biconjugate gradients, stabilized.
    [x, flag, relres, iter, resvec] = bicgstab(A, b, tol, maxit, M1, M2, x0)
cgs: Solve A*x = b by conjugate gradients squared.
    [x, flag, relres, iter, resvec] = cgs(A, b, tol, maxit, M1, M2, x0)
gmres: Solve A*x = b by the generalized minimum residual method, with restarts.
    x = gmres(A, b)
    [x, flag, relres, iter, resvec] = gmres(A, b, restart, tol, maxit, M1, M2, x0)
    * iter is [outer inner].
minres: Solve A*x = b for a symmetric A by the minimum residual method.
    [x, flag, relres, iter, resvec] = minres(A, b, tol, maxit, M1, M2, x0)
qmr: Solve A*x = b by the quasi-minimal residual method.
    [x, flag, relres, iter, resvec] = qmr(A, b, tol, maxit, M1, M2, x0)
tfqmr: Solve A*x = b by the transpose-free quasi-minimal residual method.
    [x, flag, relres, iter, resvec] = tfqmr(A, b, tol, maxit, M1, M2, x0)
lsqr: Least squares solution of A*x = b by LSQR.
    x = lsqr(A, b)
    [x, flag, relres, iter, resvec] = lsqr(A, b, tol, maxit, M1, M2, x0)
cholupdate: Update the Cholesky factor after adding (or removing) x*x'.
    R1 = cholupdate(R, x)
    [R1, p] = cholupdate(R, x, '-')
qrupdate: Update a QR factorization after adding u*v'.
    [Q1, R1] = qrupdate(Q, R, u, v)
qrinsert: Update a QR factorization after inserting a column or a row.
    [Q1, R1] = qrinsert(Q, R, j, x)
    [Q1, R1] = qrinsert(Q, R, j, x, 'row')
qrdelete: Update a QR factorization after deleting a column or a row.
    [Q1, R1] = qrdelete(Q, R, j)
    [Q1, R1] = qrdelete(Q, R, j, 'row')
qz: The generalized Schur (QZ) factorization of a pair of matrices.
    [AA, BB, Q, Z] = qz(A, B)
    [AA, BB, Q, Z, V, W] = qz(A, B, 'real')
    * Q*A*Z = AA and Q*B*Z = BB.
ordschur: Reorder a Schur factorization so that chosen eigenvalues come first.
    [US, TS] = ordschur(U, T, select)
    [US, TS] = ordschur(U, T, keys)
ordeig: The eigenvalues of a (quasi-)triangular matrix in the order of its diagonal.
    e = ordeig(T)
    e = ordeig(AA, BB)
ordqz: Reorder a QZ factorization so that chosen eigenvalues come first.
    [AAS, BBS, QS, ZS] = ordqz(AA, BB, Q, Z, select)
    [AAS, BBS, QS, ZS] = ordqz(AA, BB, Q, Z, keyword)
    [AAS, BBS, QS, ZS] = ordqz(AA, BB, Q, Z, keys)
    * keyword: 'lhp' (real part below 0), 'rhp' (above 0), 'udi' (inside the unit disk), 'udo' (outside).
    * QS*A*ZS = AAS and QS*B*ZS = BBS.
rsf2csf: A real Schur form turned into the complex one.
    [U, T] = rsf2csf(Ur, Tr)
    * T is upper triangular and U*T*U' is Ur*Tr*Ur'.
gsvd: The generalized singular value decomposition of a pair of matrices.
    sigma = gsvd(A, B)
    [U, V, X, C, S] = gsvd(A, B)
    [U, V, X, C, S] = gsvd(A, B, 0)
    * A = U*C*X', B = V*S*X' and C'*C + S'*S = I, with U and V unitary.
    * sigma, sqrt(diag(C'*C)./diag(S'*S)), is in increasing order; gsvd(A, B, 0) or 'econ' gives the economy size.
gallery: Test matrices, by name.
    A = gallery(name, n)
    A = gallery(name, n, ...)
    * Names: binomial, cauchy, chebvand, chow, circul, clement, compar, cycol, fiedler, forsythe, frank, gcdmat, gearmat, grcar, hanowa, house, invhess, invol, ipjfact, jordbloc, kahan, kms, krylov, lauchli, lehmer, leslie, lesp, lotkin, minij, moler, neumann, orthog, parter, pei, poisson, prolate, randhess, rando, randsvd, redheff, riemann, ris, smoke, toeppd, toeppen, tridiag, triw, wilk (21), and the data sets integerdata, uniformdata and normaldata.
    * neumann, poisson, toeppen and tridiag are sparse. The random ones come from rand's generator; the data sets from one of their own, seeded by their last input.
polyeig: Eigenvalues of a matrix polynomial.
    e = polyeig(A0, A1, ..., Ap)
    [X, e] = polyeig(...)
    [X, e, s] = polyeig(...)
    * Solves (A0 + e*A1 + ... + e^p*Ap)*x = 0.
# ---- geometry and interpolation objects -------------------------------------------------------------
delaunay: The Delaunay triangulation of points (tetrahedra in 3-D).
    T = delaunay(x, y)
    T = delaunay(x, y, z)
    T = delaunay(P)
convhull: The convex hull of points, and its area or volume.
    K = convhull(x, y)
    [K, A] = convhull(x, y)
    [K, V] = convhull(x, y, z)
    K = convhull(..., 'Simplify', false)
    * In 2-D, K is a closed loop of point indices, counterclockwise.
voronoi: Draw the Voronoi diagram of points, or give its edges.
    voronoi(x, y)
    [vx, vy] = voronoi(x, y)
voronoin: The Voronoi vertices and cells of points in any dimension.
    [V, C] = voronoin(X)
    * V(1, :) is Inf: a cell that holds index 1 is unbounded.
tsearchn: The simplex enclosing each point, and its barycentric coordinates.
    t = tsearchn(X, T, XI)
    [t, p] = tsearchn(X, T, XI)
dsearchn: The nearest point of a set to each query point.
    k = dsearchn(X, XI)
    [k, d] = dsearchn(X, XI)
    k = dsearchn(X, T, XI, outval)
rectint: The areas where rectangles [x y width height] overlap.
    area = rectint(A, B)
interp3: Interpolation of 3-D data in meshgrid's layout.
    Vq = interp3(X, Y, Z, V, Xq, Yq, Zq)
    Vq = interp3(V, Xq, Yq, Zq)
    Vq = interp3(..., method, extrapval)
griddedInterpolant: An interpolant of values on a grid, evaluated as F(xq).
    F = griddedInterpolant(x, v)
    F = griddedInterpolant({x1, x2}, V)
    F = griddedInterpolant(X1, X2, V, method, extrapolation)
    vq = F(xq1, xq2)
    Vq = F({xg1, xg2})
    * Methods: 'linear' (the default), 'nearest', 'next', 'previous', 'pchip', 'cubic', 'spline', 'makima'; extrapolation by the method unless given ('none' gives NaN).
scatteredInterpolant: An interpolant of values at scattered points, evaluated as F(xq, yq).
    F = scatteredInterpolant(x, y, v)
    F = scatteredInterpolant(P, v, method, extrapolation)
    vq = F(xq, yq)
    * Methods: 'linear' (the default), 'nearest', 'natural' (computed as 'linear' here); extrapolation 'linear', 'nearest' or 'none'.
triplot: Draw the edges of triangles.
    triplot(TRI, x, y)
    triplot(TRI, x, y, spec)
trisurf: Draw triangles as a surface.
    trisurf(TRI, x, y, z)
    trisurf(TRI, x, y, z, c)
trimesh: Draw triangles as a mesh.
    trimesh(TRI, x, y, z)
    trimesh(TRI, x, y, z, c)
# ---- images and colours ---------------------------------------------------------------------------
im2double: An image as double, its values from 0 to 1.
    D = im2double(I)
    D = im2double(X, 'indexed')
    * uint8 values are divided by 255, uint16 by 65535, int16 shifted by 32768 first; logical and single become 0 and 1, double stays. An indexed image ('indexed') of class uint8 or uint16 counts its colours from 0, so 1 is added.
im2single: An image as single, its values from 0 to 1.
    S = im2single(I)
    S = im2single(X, 'indexed')
im2uint8: An image as uint8, its values from 0 to 255.
    U = im2uint8(I)
    U = im2uint8(X, 'indexed')
    * double and single values are clipped to 0 to 1, times 255 and rounded (NaN becomes 0). An indexed image of class double counts its colours from 1, so 1 is taken away.
im2uint16: An image as uint16, its values from 0 to 65535.
    U = im2uint16(I)
    U = im2uint16(X, 'indexed')
rgb2gray: An RGB image or colormap made gray.
    I = rgb2gray(RGB)
    newmap = rgb2gray(map)
    * Each pixel's gray level is 0.2989 R + 0.5870 G + 0.1140 B (the luma of NTSC's YIQ), of the class of RGB. A colormap gives a colormap of the gray levels.
im2gray: An image made gray: an RGB image as rgb2gray makes it, a gray image as it is.
    I = im2gray(A)
cmap2gray: A colormap made gray: each colour's gray level (as rgb2gray gives it) in all three columns.
    newmap = cmap2gray(map)
mat2gray: A matrix scaled to a gray image from 0 to 1.
    I = mat2gray(A)
    I = mat2gray(A, [amin amax])
    * amin becomes 0 and amax 1 (the least and largest values of A unless given); values beyond are clipped. A matrix with no range keeps its values, clipped to 0 to 1.
rgb2hsv: RGB colours as hue, saturation and value.
    HSV = rgb2hsv(RGB)
    hsvmap = rgb2hsv(map)
    * Each is from 0 to 1: the hue goes round red (0), yellow (1/6), green (1/3), cyan (1/2), blue (2/3) and magenta (5/6); a gray has hue and saturation 0. uint8 and uint16 colours are scaled to 0 to 1 first; single stays single.
hsv2rgb: Hue, saturation and value as RGB colours.
    RGB = hsv2rgb(HSV)
    rgbmap = hsv2rgb(hsvmap)
rgb2lightness: The lightness L* of RGB colours, from 0 (black) to 100 (white).
    L = rgb2lightness(RGB)
    L = rgb2lightness(map)
    * The colours are sRGB, the white D65; L* is CIE 1976 L*a*b*'s. An M-by-N-by-3 image gives an M-by-N array, a c-by-3 colormap a column.
ind2rgb: An indexed image as an RGB image.
    RGB = ind2rgb(X, map)
    * X of class double counts the colours of map from 1, uint8 and uint16 from 0; indices past the ends take the first or last colour. RGB is double.
ind2gray: An indexed image as a gray image, each colour's gray level as rgb2gray gives it.
    I = ind2gray(X, map)
    * I has the class of X.
gray2ind: A gray or binary image as an indexed image of gray levels.
    [X, map] = gray2ind(I)
    [X, map] = gray2ind(I, n)
    * n levels (64 for a gray image, 2 for a binary one); map is gray(n). X is uint8, or uint16 for more than 256 levels, counting from 0.
rgb2ind: An RGB image as an indexed image.
    [X, map] = rgb2ind(RGB, n)
    [X, map] = rgb2ind(RGB, tol)
    X = rgb2ind(RGB, map)
    [...] = rgb2ind(..., 'nodither')
    * n: at most n colours, chosen by minimum variance quantization. tol, from 0 to 1: floor(1/tol)+1 levels a channel, the colours no pixel takes left out. map: the colours of a colormap given.
    * Unless 'nodither', the colours are dithered (Floyd-Steinberg), so that areas keep their average colour. X is uint8 (uint16 for more than 256 colours), counting from 0.
imsplit: The channels of a multichannel image, each as an array of its own.
    [c1, c2, c3] = imsplit(RGB)
    [c1, ..., ck] = imsplit(I)

# ---- images, sound and the web ------------------------------------------------------------------
imread: Read an image file.
    A = imread(filename)
    [X, map] = imread(filename)
    [A, map, alpha] = imread(filename)
    * PNG, JPEG, BMP, TIFF and GIF; uint8 (uint16 for 16-bit images), m-by-n for gray, m-by-n-by-3 for colour; an image with a palette gives indices from 0 and its colormap.
imwrite: Write an image file.
    imwrite(A, filename)
    imwrite(X, map, filename)
    imwrite(..., 'Quality', q)
    imwrite(..., 'Alpha', alpha)
    * The format comes from the name (or is given); doubles are taken as 0 to 1.
imfinfo: Facts about an image file.
    info = imfinfo(filename)
audioread: Read a WAV file.
    [y, Fs] = audioread(filename)
    [y, Fs] = audioread(filename, [start stop])
    [y, Fs] = audioread(filename, 'native')
audiowrite: Write a WAV file.
    audiowrite(filename, y, Fs)
    audiowrite(filename, y, Fs, 'BitsPerSample', 24)
audioinfo: Facts about a WAV file.
    info = audioinfo(filename)
webread: Read data from a web address (JSON, text, an image, or bytes).
    data = webread(url)
    data = webread(url, QueryName, QueryValue)
    data = webread(..., options)
    * In the page, only servers that allow it (CORS) can be read.
webwrite: Send data to a web address and read the answer.
    response = webwrite(url, PostName, PostValue)
    response = webwrite(url, data)
    response = webwrite(..., options)
websave: Save what a web address gives to a file.
    filename = websave(filename, url)
weboptions: Options for webread, webwrite and websave.
    options = weboptions('Timeout', 10)
    options = weboptions('ContentType', 'json', 'HeaderFields', {'Accept', 'application/json'})
# ---- more plots -------------------------------------------------------------------------------------
compass: Arrows from the origin, in polar axes.
    compass(U, V)
    compass(Z)
feather: Arrows from equally spaced points along the x-axis.
    feather(U, V)
    feather(Z)
rose: An angle histogram in polar axes.
    rose(theta)
    rose(theta, nbins)
    [tout, rout] = rose(...)
pareto: Bars in descending order with their cumulative percentage.
    pareto(y)
    pareto(y, names)
    pareto(y, names, threshold)
    [H, ax] = pareto(...)
stem3: Stems from z = 0 with markers, in 3-D.
    stem3(Z)
    stem3(X, Y, Z)
    stem3(..., 'filled')
comet: The path of a point with its head.
    comet(y)
    comet(x, y)
    * Drawn whole: the figure shows the path as it ends.
comet3: The path of a point in 3-D with its head.
    comet3(x, y, z)
bar3: Three-dimensional bars.
    bar3(Z)
    bar3(y, Z, width)
    bar3(..., 'grouped')
    bar3(..., 'stacked')
bar3h: Three-dimensional bars along the x-axis.
    bar3h(Z)
histogram2: A bivariate histogram drawn as 3-D bars.
    histogram2(X, Y)
    histogram2(X, Y, nbins)
    histogram2(X, Y, Xedges, Yedges)
pie3: A three-dimensional pie chart.
    pie3(x)
    pie3(x, explode)
    pie3(x, explode, labels)
ribbon: Columns of data as ribbons in 3-D.
    ribbon(Y)
    ribbon(X, Y, width)
isosurface: The surface where volume data has a given value.
    fv = isosurface(X, Y, Z, V, isovalue)
    [faces, verts] = isosurface(V, isovalue)
    isosurface(...)
slice: Volume data shown on planes through it.
    slice(X, Y, Z, V, xslice, yslice, zslice)
    slice(V, xslice, yslice, zslice)
stream2: Streamlines of a 2-D vector field.
    XY = stream2(X, Y, U, V, startx, starty)
    XY = stream2(..., [step maxvert])
stream3: Streamlines of a 3-D vector field.
    XYZ = stream3(X, Y, Z, U, V, W, startx, starty, startz)
streamline: Draw streamlines of a vector field.
    streamline(X, Y, U, V, startx, starty)
    streamline(X, Y, Z, U, V, W, startx, starty, startz)
    streamline(XY)
camorbit: Turn the view about the axes' centre.
    camorbit(dtheta, dphi)
campos: Where the camera is, or put it somewhere.
    p = campos
    campos([x y z])
    * The camera looks at camtarget, the middle of the axes unless set.
camtarget: The point the camera looks at, which stands in the middle of the axes.
    t = camtarget
    camtarget([x y z])
    camtarget('auto')
    m = camtarget('mode')
camup: The direction that points up on the screen.
    u = camup
    camup([x y z])
    camup('auto')
    * [0 0 1] unless set: the z axis up.
camroll: Turn the view about its axis.
    camroll(dtheta)
    * A positive angle turns the picture counterclockwise.
coneplot: Cones that show a 3-D vector field at given points.
    coneplot(X, Y, Z, U, V, W, Cx, Cy, Cz)
    coneplot(U, V, W, Cx, Cy, Cz)
    coneplot(..., s)
    coneplot(..., 'nointerp')
    coneplot(..., 'quiver')
    h = coneplot(...)
    * Each cone points along the field at its point (interpolated, linear unless 'nearest' or 'cubic' is given) and is as long as the speed there; s scales them, 1 making the fastest about as long as the points are apart. The cones are one patch, coloured by speed.
streamtube: Tubes round the streamlines of a 3-D vector field.
    streamtube(X, Y, Z, U, V, W, startx, starty, startz)
    streamtube(XYZ)
    streamtube(..., [scale n])
    h = streamtube(...)
    * The tube's width follows the field's divergence along the line (constant for a cell of vertices from stream3); scale sets it (1), n the number of points round the tube (20).
contourslice: Contour lines of a volume on slice planes.
    contourslice(X, Y, Z, V, Sx, Sy, Sz)
    contourslice(V, Sx, Sy, Sz)
    contourslice(..., levels)
    h = contourslice(...)
    * levels is the number of levels or the levels themselves. Each line is a patch with no face, its edge coloured by its level.
# ---- signal processing ---------------------------------------------------------------------------
butter: A Butterworth filter (maximally flat passband).
    [b, a] = butter(n, Wn)
    [b, a] = butter(n, Wn, ftype)
    [z, p, k] = butter(...)
    [A, B, C, D] = butter(...)
    [b, a] = butter(n, Wn, 's')
    * Wn is the cutoff, 1 being half the sampling rate; two values make a bandpass filter (order 2n). ftype is 'low', 'high', 'bandpass' or 'stop'; 's' designs an analog filter (Wn in rad/s).
cheby1: A Chebyshev type I filter: Rp dB of ripple in the passband.
    [b, a] = cheby1(n, Rp, Wp)
    [b, a] = cheby1(n, Rp, Wp, ftype)
    [z, p, k] = cheby1(...)
cheby2: A Chebyshev type II filter: the stopband Rs dB down.
    [b, a] = cheby2(n, Rs, Ws)
    [b, a] = cheby2(n, Rs, Ws, ftype)
    [z, p, k] = cheby2(...)
ellip: An elliptic filter: Rp dB of passband ripple, the stopband Rs dB down.
    [b, a] = ellip(n, Rp, Rs, Wp)
    [b, a] = ellip(n, Rp, Rs, Wp, ftype)
    [z, p, k] = ellip(...)
buttord: The lowest Butterworth order (and its cutoff) that meets a passband and stopband.
    [n, Wn] = buttord(Wp, Ws, Rp, Rs)
    [n, Wn] = buttord(Wp, Ws, Rp, Rs, 's')
cheb1ord: The lowest Chebyshev type I order that meets a passband and stopband.
    [n, Wp] = cheb1ord(Wp, Ws, Rp, Rs)
cheb2ord: The lowest Chebyshev type II order that meets a passband and stopband.
    [n, Ws] = cheb2ord(Wp, Ws, Rp, Rs)
ellipord: The lowest elliptic order that meets a passband and stopband.
    [n, Wp] = ellipord(Wp, Ws, Rp, Rs)
fir1: A window-method FIR filter of order n (a Hamming window unless given one).
    b = fir1(n, Wn)
    b = fir1(n, Wn, ftype)
    b = fir1(n, Wn, ftype, window)
    b = fir1(..., 'noscale')
    * ftype is 'low', 'high', 'bandpass', 'stop', 'DC-0' or 'DC-1'. A highpass or bandstop filter's odd order is made one higher. The filter is scaled to 1 in the middle of its first passband.
fir2: An FIR filter of order n with magnitudes m at the frequencies f (from 0 to 1).
    b = fir2(n, f, m)
    b = fir2(n, f, m, npt)
    b = fir2(n, f, m, window)
firls: The least-squares FIR filter of order n for bands f with amplitudes a.
    b = firls(n, f, a)
    b = firls(n, f, a, w)
    * The order must be even here.
firpm: The equiripple (Parks-McClellan) FIR filter of order n for bands f with amplitudes a.
    b = firpm(n, f, a)
    b = firpm(n, f, a, w)
    b = firpm(n, f, a, 'hilbert')
    b = firpm(n, f, a, 'differentiator')
    * Each band has one amplitude here (a(k) = a(k+1)).
remez: The equiripple FIR filter (the name firpm had before; the same).
    b = remez(n, f, a)
kaiserord: The order, cutoff and Kaiser beta for a window-method design that meets band edges f, amplitudes a and deviations dev.
    [n, Wn, beta, ftype] = kaiserord(f, a, dev)
    [n, Wn, beta, ftype] = kaiserord(f, a, dev, fs)
    * Then b = fir1(n, Wn, ftype, kaiser(n+1, beta), 'noscale').
filtfilt: Zero-phase filtering: forward, then backward, so nothing is delayed.
    y = filtfilt(b, a, x)
    y = filtfilt(sos, g, x)
    y = filtfilt(d, x)
    * The ends are extended by odd reflection, 3 times the filter order, and the filter starts in its steady state. The magnitude response is the filter's squared.
sosfilt: Filtering by second-order sections (each row b0 b1 b2 a0 a1 a2).
    y = sosfilt(sos, x)
fftfilt: FIR filtering by the FFT (overlap-add): what filter(b, 1, x) gives.
    y = fftfilt(b, x)
filtic: Initial conditions for filter from past outputs and inputs.
    zi = filtic(b, a, y)
    zi = filtic(b, a, y, x)
    * y and x hold the latest past value first: y(1) is y(-1).
upfirdn: Upsampling by p, FIR filtering by h and downsampling by q.
    y = upfirdn(x, h)
    y = upfirdn(x, h, p, q)
medfilt1: A median filter: each sample the median of the n about it (n = 3).
    y = medfilt1(x)
    y = medfilt1(x, n)
    y = medfilt1(x, n, [], dim)
    y = medfilt1(..., 'truncate')
    * Beyond the ends the signal is taken as zeros ('zeropad'), or the windows are cut short ('truncate'). For an even n the window is x(k-n/2 : k+n/2-1).
sgolay: The Savitzky-Golay projection matrix B and differentiation filters G for a polynomial order and an odd frame length.
    B = sgolay(order, framelen)
    [B, G] = sgolay(order, framelen)
sgolayfilt: Savitzky-Golay smoothing: each sample the value of a polynomial fitted about it.
    y = sgolayfilt(x, order, framelen)
hilbert: The analytic signal x + i*H(x), H the Hilbert transform.
    y = hilbert(x)
    y = hilbert(x, n)
    * abs(y) is the envelope, angle(y) the instantaneous phase.
envelope: Upper and lower envelopes of a signal.
    [up, lo] = envelope(x)
    [up, lo] = envelope(x, np, 'peak')
    envelope(x)
    * By default from the analytic signal of x less its mean; 'peak' joins local maxima (and minima) at least np samples apart by splines.
xcorr: Cross-correlation: r(m) is the sum of x(n+m)*conj(y(n)), at lags -(N-1) to N-1.
    r = xcorr(x, y)
    r = xcorr(x)
    [r, lags] = xcorr(..., maxlag)
    r = xcorr(..., scaleopt)
    * scaleopt is 'none', 'biased' (divided by N), 'unbiased' (by N-|m|) or 'normalized' (1 at lag 0 for xcorr(x)). The shorter signal is padded with zeros. For a matrix, every pair of columns.
xcov: Cross-covariance: xcorr of the signals less their means.
    c = xcov(x, y)
    [c, lags] = xcov(x, maxlag, scaleopt)
resample: A signal at p/q times its sampling rate, by polyphase filtering.
    y = resample(x, p, q)
decimate: A signal lowpass filtered (a Chebyshev type I filter of order 8, both ways) and every r-th sample kept.
    y = decimate(x, r)
    y = decimate(x, r, n)
    y = decimate(x, r, 'fir')
    * The samples kept are the first and every r-th after it.
interp: A signal with r times as many samples, by lowpass interpolation; its own samples are kept.
    y = interp(x, r)
downsample: Every n-th sample, from sample phase+1.
    y = downsample(x, n)
    y = downsample(x, n, phase)
upsample: n-1 zeros put after each sample.
    y = upsample(x, n)
    y = upsample(x, n, phase)
buffer: A signal cut into frames (columns) of n samples, each overlapping the one before by p (or skipping -p between them).
    y = buffer(x, n)
    y = buffer(x, n, p)
    [y, z] = buffer(...)
    * With p > 0 the first frame starts with p zeros; the last is padded with zeros, or with two outputs left out and given as z.
findpeaks: Local maxima of a signal: their values, where they are, their widths and prominences.
    pks = findpeaks(y)
    [pks, locs] = findpeaks(y, x)
    [pks, locs, w, p] = findpeaks(y, fs)
    [...] = findpeaks(..., 'MinPeakHeight', h, 'MinPeakProminence', p, 'MinPeakDistance', d, 'Threshold', t, 'NPeaks', n, 'SortStr', 'descend', 'MinPeakWidth', w, 'MaxPeakWidth', w, 'WidthReference', 'halfheight')
    findpeaks(y)
    * A peak is higher than both neighbours (a flat one is where it starts; the ends never are). Widths are measured at half the prominence (or half the height), between linear crossings. MinPeakDistance keeps the highest peaks first. With no output the signal is plotted with the peaks marked.
hamming: A Hamming window (a column).
    w = hamming(n)
    w = hamming(n, 'periodic')
hann: A Hann window, with its zero ends.
    w = hann(n)
    w = hann(n, 'periodic')
hanning: A Hann window without its zero ends.
    w = hanning(n)
blackman: A Blackman window.
    w = blackman(n)
    w = blackman(n, 'periodic')
flattopwin: A flat-top window (for measuring amplitudes).
    w = flattopwin(n)
blackmanharris: A minimum four-term Blackman-Harris window.
    w = blackmanharris(n)
nuttallwin: A Nuttall four-term Blackman-Harris window.
    w = nuttallwin(n)
kaiser: A Kaiser window with shape beta (0.5).
    w = kaiser(n, beta)
bartlett: A Bartlett (triangular, zero at its ends) window.
    w = bartlett(n)
triang: A triangular window not zero at its ends.
    w = triang(n)
rectwin: A rectangular window: ones.
    w = rectwin(n)
gausswin: A Gaussian window, alpha (2.5) the reciprocal of its standard deviation.
    w = gausswin(n, alpha)
tukeywin: A tapered-cosine window, r (0.5) the part of it tapered.
    w = tukeywin(n, r)
chebwin: A Chebyshev window, its sidelobes r dB (100) down.
    w = chebwin(n, r)
barthannwin: A modified Bartlett-Hann window.
    w = barthannwin(n)
bohmanwin: A Bohman window.
    w = bohmanwin(n)
parzenwin: A Parzen (de la Vallee Poussin) window.
    w = parzenwin(n)
window: A window by its function.
    w = window(@hamming, n)
    w = window(@kaiser, n, beta)
freqz: A digital filter's frequency response.
    [h, w] = freqz(b, a)
    [h, w] = freqz(b, a, n)
    [h, w] = freqz(b, a, n, 'whole')
    [h, f] = freqz(b, a, n, fs)
    h = freqz(b, a, w)
    freqz(b, a)
    * n points (512) from 0 up to half the sampling rate (pi rad/sample), or the whole circle. sos and digital filters too. With no output, magnitude (dB) and phase (degrees) are plotted.
freqs: An analog filter's frequency response.
    [h, w] = freqs(b, a, w)
    [h, w] = freqs(b, a, n)
    freqs(b, a)
impz: A filter's impulse response.
    [h, t] = impz(b, a)
    [h, t] = impz(b, a, n)
    [h, t] = impz(b, a, n, fs)
    impz(b, a)
    * Without n, an FIR filter's length, or an IIR filter's response until it has died away (below 5e-5 of its largest).
stepz: A filter's step response.
    [s, t] = stepz(b, a)
    [s, t] = stepz(b, a, n)
grpdelay: A filter's group delay, in samples.
    [gd, w] = grpdelay(b, a)
    [gd, w] = grpdelay(b, a, n)
zplane: A filter's zeros (o) and poles (x) in the complex plane, with the unit circle.
    zplane(b, a)
    zplane(z, p)
    * Rows are a transfer function's coefficients; columns are zeros and poles.
tf2zp: A transfer function's zeros, poles and gain.
    [z, p, k] = tf2zp(b, a)
zp2tf: A transfer function from zeros, poles and gain.
    [b, a] = zp2tf(z, p, k)
tf2sos: Second-order sections of a transfer function.
    sos = tf2sos(b, a)
    [sos, g] = tf2sos(b, a)
zp2sos: Second-order sections from zeros, poles and gain.
    sos = zp2sos(z, p, k)
    [sos, g] = zp2sos(z, p, k)
sos2tf: The transfer function of second-order sections.
    [b, a] = sos2tf(sos)
    [b, a] = sos2tf(sos, g)
sos2zp: The zeros, poles and gain of second-order sections.
    [z, p, k] = sos2zp(sos)
    [z, p, k] = sos2zp(sos, g)
filtord: A filter's order.
    n = filtord(b, a)
    n = filtord(d)
designfilt: A digital filter from a response and its specifications.
    d = designfilt('lowpassfir', 'FilterOrder', n, 'CutoffFrequency', fc, 'SampleRate', fs)
    d = designfilt('lowpassiir', 'FilterOrder', n, 'HalfPowerFrequency', f3db)
    d = designfilt('bandpassiir', 'FilterOrder', n, 'HalfPowerFrequency1', f1, 'HalfPowerFrequency2', f2)
    d = designfilt('highpassfir', 'PassbandFrequency', fp, 'StopbandFrequency', fst, 'StopbandAttenuation', a)
    * Responses: lowpass, highpass, bandpass and bandstop, each fir or iir. FIR filters by the window method (FilterOrder and CutoffFrequency, Window), or from passband and stopband edges by a Kaiser window; IIR filters by butter (DesignMethod 'cheby1', 'cheby2' or 'ellip' instead), kept as second-order sections. filter(d, x), filtfilt(d, x), freqz(d), impz(d), zplane(d) and filtord(d) take them; d.Coefficients holds them.
lowpass: A signal lowpass filtered, its delay taken back.
    y = lowpass(x, wpass)
    y = lowpass(x, fpass, fs)
    [y, d] = lowpass(...)
    y = lowpass(..., 'Steepness', s, 'StopbandAttenuation', a)
    * A Kaiser-window FIR filter, the stopband 60 dB down and the transition band 15 % of the way from the passband edge to half the sampling rate (Steepness 0.85).
highpass: A signal highpass filtered, its delay taken back.
    y = highpass(x, wpass)
    y = highpass(x, fpass, fs)
bandpass: A signal bandpass filtered, its delay taken back.
    y = bandpass(x, [w1 w2])
    y = bandpass(x, [f1 f2], fs)
bandstop: A signal with a band taken out, its delay taken back.
    y = bandstop(x, [w1 w2])
    y = bandstop(x, [f1 f2], fs)
periodogram: The power spectral density by the periodogram.
    [pxx, w] = periodogram(x)
    [pxx, w] = periodogram(x, window, nfft)
    [pxx, f] = periodogram(x, window, nfft, fs)
    [...] = periodogram(..., 'twosided')
    periodogram(x)
    * A rectangular window unless given one, nfft = max(256, 2^nextpow2(N)), one-sided for real signals; w in rad/sample (or f in Hz with fs). With no output the estimate is plotted in dB.
pwelch: The power spectral density by Welch's method: windowed segments' periodograms averaged.
    [pxx, w] = pwelch(x)
    [pxx, w] = pwelch(x, window, noverlap, nfft)
    [pxx, f] = pwelch(x, window, noverlap, nfft, fs)
    pwelch(x)
    * By default 8 segments with half overlapping, each a Hamming window long.
cpsd: The cross power spectral density by Welch's method.
    [pxy, w] = cpsd(x, y)
    [pxy, f] = cpsd(x, y, window, noverlap, nfft, fs)
mscohere: The magnitude-squared coherence of two signals, from 0 to 1 at each frequency.
    [cxy, w] = mscohere(x, y)
    [cxy, f] = mscohere(x, y, window, noverlap, nfft, fs)
tfestimate: The transfer function from x to y: their cross spectrum over the spectrum of x.
    [txy, w] = tfestimate(x, y)
    [txy, f] = tfestimate(x, y, window, noverlap, nfft, fs)
spectrogram: The short-time Fourier transform: a spectrum for each windowed segment.
    s = spectrogram(x)
    [s, w, t] = spectrogram(x, window, noverlap, nfft)
    [s, f, t, ps] = spectrogram(x, window, noverlap, nfft, fs)
    spectrogram(x)
    * By default 8 segments with half overlapping, Hamming windows. t gives each segment's middle; ps the power spectral density. With no output it is drawn as an image in dB.
bandpower: Average power, of a signal or within a band.
    p = bandpower(x)
    p = bandpower(x, fs, freqrange)
    p = bandpower(pxx, f, 'psd')
    p = bandpower(pxx, f, freqrange, 'psd')
chirp: A swept-frequency cosine, f0 at time 0 to f1 at time t1.
    y = chirp(t, f0, t1, f1)
    y = chirp(t, f0, t1, f1, method)
    y = chirp(t, f0, t1, f1, method, phi)
    * method is 'linear', 'quadratic' or 'logarithmic'; phi is the initial phase in degrees.
sawtooth: A sawtooth wave of period 2*pi, from -1 to 1.
    x = sawtooth(t)
    x = sawtooth(t, xmax)
    * xmax (1) is where in the period it peaks: 0.5 makes a triangle wave.
square: A square wave of period 2*pi, 1 for duty percent (50) of the period and -1 after.
    x = square(t)
    x = square(t, duty)
rectpuls: A rectangular pulse of width w (1) about t = 0.
    y = rectpuls(t)
    y = rectpuls(t, w)
tripuls: A triangular pulse of width w (1), its peak at s*w/2.
    y = tripuls(t)
    y = tripuls(t, w, s)
gauspuls: A Gaussian-modulated sinusoid of centre frequency fc (1000 Hz) and relative bandwidth bw (0.5).
    yi = gauspuls(t, fc, bw)
    [yi, yq, ye] = gauspuls(t, fc, bw, bwr)
diric: The Dirichlet (periodic sinc) function sin(n*x/2)/(n*sin(x/2)).
    y = diric(x, n)
db2mag: Decibels as magnitudes: 10^(y/20).
    y = db2mag(ydb)
mag2db: Magnitudes in decibels: 20*log10(y).
    ydb = mag2db(y)
pow2db: Powers in decibels: 10*log10(y).
    ydb = pow2db(y)
db2pow: Decibels as powers: 10^(y/10).
    y = db2pow(ydb)
peak2peak: The largest value less the smallest.
    y = peak2peak(x)
    y = peak2peak(x, dim)
peak2rms: The largest magnitude over the root mean square.
    y = peak2rms(x)
    y = peak2rms(x, dim)
rceps: The real cepstrum, and the minimum-phase signal with the same magnitude spectrum.
    y = rceps(x)
    [y, ym] = rceps(x)
dct: The orthonormal discrete cosine transform (type II).
    y = dct(x)
    y = dct(x, n)
    y = dct(x, n, dim)
    y = dct(..., 'Type', k)
idct: The inverse discrete cosine transform.
    x = idct(y)
    x = idct(y, n, dim)

# ---- regression and curve fitting ------------------------------------------------------------------------------------------
fitlm: A linear regression model: least squares of a response on its predictors.
    mdl = fitlm(X, y)
    mdl = fitlm(X, y, modelspec)
    mdl = fitlm(tbl)
    mdl = fitlm(tbl, 'y ~ x1 + x2*x3')
    mdl = fitlm(..., 'Intercept', false, 'Weights', w, 'RobustOpts', 'on', 'CategoricalVars', vars, 'VarNames', names, 'Exclude', rows)
    * modelspec is 'constant', 'linear' (the default), 'interactions', 'purequadratic', 'quadratic' or 'polyN', or a formula: + adds a term, - takes one away, * gives the terms and their products, : a product alone, ^ a power, and -1 leaves the intercept out. A categorical predictor becomes a dummy for each level but the first. With a table the last variable is the response unless ResponseVar says which.
    * mdl.Coefficients is a table of Estimate, SE, tStat and pValue; mdl.Rsquared, mdl.RMSE, mdl.Residuals, mdl.Fitted, mdl.ModelCriterion, mdl.CoefficientCovariance and the rest are read as properties. Showing the model shows its formula, the table, R-squared and the F-statistic against the constant model.
fitglm: A generalized linear model: a response from the normal, binomial, Poisson, gamma or inverse Gaussian distribution, its mean a function of the linear predictor.
    mdl = fitglm(X, y)
    mdl = fitglm(X, y, modelspec, 'Distribution', 'poisson')
    mdl = fitglm(X, [k n], 'linear', 'Distribution', 'binomial')
    mdl = fitglm(tbl, 'y ~ x1 + x2', 'Distribution', 'binomial', 'Link', 'probit')
    mdl = fitglm(..., 'BinomialSize', n, 'Weights', w, 'Offset', o, 'DispersionFlag', true)
    * The link is the distribution's canonical one unless Link names another ('identity', 'log', 'logit', 'probit', 'comploglog', 'loglog', 'reciprocal' or a power). A binomial response is a proportion with BinomialSize, or two columns of successes and trials. mdl.Deviance, mdl.Dispersion and the coefficients' table are read as properties; predict gives the mean.
fitnlm: A nonlinear regression model: least squares of a model function's coefficients.
    mdl = fitnlm(X, y, modelfun, beta0)
    mdl = fitnlm(tbl, modelfun, beta0)
    mdl = fitnlm(..., 'Weights', w, 'CoefficientNames', names)
    * modelfun(b, X) gives the fitted values for coefficients b (a column for each predictor in X).
predict: Predictions of a fitted model, with confidence bounds.
    ypred = predict(mdl, Xnew)
    [ypred, yci] = predict(mdl, Xnew)
    [ypred, yci] = predict(mdl, Xnew, 'Alpha', 0.05, 'Prediction', 'observation', 'Simultaneous', true)
    [label, score] = predict(Mdl, X)
    [ypred, ysd, yint] = predict(gprMdl, Xnew)
    * The bounds are for the curve (the mean) unless Prediction is 'observation', which adds the residual variance. Xnew is a matrix of predictors or a table with the model's variables.
    * Of a classification model: the most probable class and each class's score; of a regression model (fitrtree, fitrsvm, ...): the predictions.
coefCI: Confidence intervals of a model's coefficients.
    ci = coefCI(mdl)
    ci = coefCI(mdl, alpha)
coefTest: A linear hypothesis test on a model's coefficients.
    p = coefTest(mdl)
    [p, F, r] = coefTest(mdl, H)
    [p, F, r] = coefTest(mdl, H, c)
    * Tests H*b = c (c is 0 unless given); with no H, that every coefficient but the intercept is 0.
anova: The analysis of variance of a linear model.
    tbl = anova(mdl)
    tbl = anova(mdl, 'summary')
    * For each term its sum of squares, degrees of freedom, mean square, F and p-value, then the error; 'summary' gives the total, the model and the residual.
plotResiduals: The residuals of a fitted model, plotted.
    plotResiduals(mdl)
    plotResiduals(mdl, 'fitted')
    plotResiduals(mdl, plottype)
    * plottype is 'histogram' (the default), 'fitted' (against the fitted values), 'caseorder', 'lagged', or 'probability' (a normal probability plot).
regress: Multiple linear regression: least squares of y on the columns of X.
    b = regress(y, X)
    [b, bint, r, rint, stats] = regress(y, X)
    [...] = regress(y, X, alpha)
    * Add a column of ones to X for an intercept. stats is [R-squared, F, its p-value, the error variance]; rint are intervals of the residuals, one that leaves out 0 marking an outlier.
robustfit: Robust linear regression: iteratively reweighted least squares.
    b = robustfit(X, y)
    [b, stats] = robustfit(X, y, wfun, tune, const)
    * wfun is 'bisquare' (the default), 'andrews', 'cauchy', 'fair', 'huber', 'logistic', 'talwar', 'welsch' or 'ols'; tune scales it. The intercept comes first unless const is 'off'. stats holds the standard errors, the weights w, the robust scale s and more.
ridge: Ridge regression.
    b = ridge(y, X, k)
    b = ridge(y, X, k, scaled)
    * A column of coefficients for each value in k. scaled 1 (the default) gives them for the predictors centred and scaled to unit standard deviation, without an intercept; scaled 0 on the data's scale, with the intercept first.
glmfit: A generalized linear model's coefficients.
    b = glmfit(X, y, distr)
    [b, dev, stats] = glmfit(X, y, distr, 'link', link, 'constant', 'off', 'weights', w, 'offset', o, 'estdisp', 'on')
    * distr is 'normal', 'binomial', 'poisson', 'gamma' or 'inverse gaussian'; a binomial y may be two columns, successes and trials. The intercept comes first.
glmval: Predictions of a generalized linear model.
    yhat = glmval(b, X, link)
    [yhat, dylo, dyhi] = glmval(b, X, link, stats)
    [...] = glmval(..., 'confidence', 0.95, 'size', n, 'offset', o, 'constant', 'off')
    * With stats from glmfit the bounds yhat - dylo and yhat + dyhi.
nlinfit: Nonlinear least squares.
    beta = nlinfit(X, y, modelfun, beta0)
    [beta, R, J, CovB, MSE] = nlinfit(X, y, modelfun, beta0)
    [...] = nlinfit(..., 'Weights', w)
    * modelfun(b, X) gives the fitted values; R are the residuals, J the Jacobian at beta, CovB the coefficients' covariance and MSE the residual variance.
nlparci: Confidence intervals of nonlinear least-squares coefficients.
    ci = nlparci(beta, R, 'Jacobian', J)
    ci = nlparci(beta, R, 'Covar', CovB)
    ci = nlparci(..., 'Alpha', alpha)
nlpredci: Predictions of a nonlinear least-squares model, with half widths of their intervals.
    [ypred, delta] = nlpredci(modelfun, X, beta, R, 'Jacobian', J)
    [ypred, delta] = nlpredci(modelfun, X, beta, R, 'Covar', CovB, 'PredOpt', 'observation', 'Alpha', alpha, 'SimOpt', 'on')
partialcorr: Partial correlations: each pair of variables with the others (or z) held fixed.
    rho = partialcorr(X)
    rho = partialcorr(x, z)
    rho = partialcorr(x, y, z)
    [rho, pval] = partialcorr(..., 'Type', 'Spearman')
randg: Gamma random numbers of shape a and scale 1.
    r = randg
    r = randg(a)
    r = randg(a, n)
    r = randg(a, m, n, ...)
    r = randg(a, [m n ...])
fit: A curve fitted to data.
    f = fit(x, y, fitType)
    [f, gof, output] = fit(x, y, fitType)
    f = fit(x, y, 'a*exp(-b*x) + c', 'StartPoint', [1 1 0])
    f = fit(x, y, fitType, 'Lower', lb, 'Upper', ub, 'Weights', w, 'Exclude', out, 'Robust', 'Bisquare')
    f = fit(x, y, 'smoothingspline', 'SmoothingParam', p)
    f = fit(x, y, fitType, opts)
    * fitType is a library model (poly1 to poly9, exp1, exp2, power1, power2, gauss1 to gauss8, sin1 to sin8, fourier1 to fourier8, rat01 to rat55, weibull), an interpolant (linearinterp, nearestinterp, pchipinterp, cubicinterp), smoothingspline, an expression in x, or a fittype. A model linear in its coefficients is solved directly; others start from the model's own guess (or StartPoint) and are fitted by nonlinear least squares within Lower and Upper. Robust is 'Off', 'Bisquare' (or 'On') or 'LAR'.
    * f(x) and feval(f, x) evaluate the fit, plot(f, x, y) draws it with its data, and f.a reads a coefficient. gof holds sse, rsquare, dfe, adjrsquare and rmse; output the residuals, the Jacobian and how the fit went. Surfaces (fit([x, y], z, ...)) are not fitted here.
fittype: A model to fit, from the library, an expression, terms or a function.
    ft = fittype(libraryName)
    ft = fittype('a*exp(-b*x) + c')
    ft = fittype('a*u + b', 'independent', 'u', 'coefficients', {'a', 'b'})
    ft = fittype({'x', 'sin(x)', '1'})
    ft = fittype(@(a, b, x) a*exp(b*x))
    * The coefficients of an expression are its names other than the independent variable and the functions it calls. A cell of terms makes a linear model with a coefficient for each (a, b, c ...). ft(a, b, ..., x) evaluates the model.
fitoptions: Options for fit, as a struct.
    opts = fitoptions('Method', 'NonlinearLeastSquares', 'StartPoint', s, 'Lower', lb, 'Upper', ub)
    opts = fitoptions(fitType)
    opts = fitoptions(fitType, 'Name', value, ...)
confint: Confidence bounds of a fit's coefficients.
    ci = confint(f)
    ci = confint(f, level)
    * A column for each coefficient: the lower bound above the upper. level is 0.95 unless given.
predint: Prediction bounds of a fit.
    ci = predint(f, x)
    [ci, y] = predint(f, x, level, intopt, simopt)
    * intopt is 'observation' (a new observation, the default) or 'functional' (the curve); simopt 'off' (each x alone, the default) or 'on' (all at once).
coeffvalues: A fit's coefficients, as a row.
    c = coeffvalues(f)
coeffnames: The names of the coefficients of a fit or fittype, as a column.
    names = coeffnames(f)
numcoeffs: How many coefficients a fit or fittype has.
    n = numcoeffs(f)
differentiate: The derivatives of a fit.
    fx = differentiate(f, x)
    [fx, fxx] = differentiate(f, x)
integrate: The integral of a fit.
    y = integrate(f, x, x0)
    * From x0 to each x.
smooth: Smoothed data, as a column.
    yy = smooth(y)
    yy = smooth(y, span)
    yy = smooth(y, method)
    yy = smooth(y, span, method)
    yy = smooth(y, span, 'sgolay', degree)
    yy = smooth(x, y, ...)
    * method is 'moving' (the default), 'lowess', 'loess', 'sgolay', 'rlowess' or 'rloess'; span is 5 points unless given, or a fraction of the data under 1. The moving average narrows its window at the ends.

# ---- features of data ---------------------------------------------------------------------------------------------------------
islocalmax: Where the local maxima of data are.
    TF = islocalmax(A)
    TF = islocalmax(A, dim)
    [TF, P] = islocalmax(..., 'MinProminence', p, 'FlatSelection', 'center', 'MinSeparation', d, 'MaxNumExtrema', n, 'SamplePoints', t)
    * A maximum is higher than the values on both sides; the ends never are. A flat top is marked at its centre, first, last or all of it. P are the prominences: how far each maximum stands above the higher of the lowest points between it and a higher one on either side. MinSeparation and MaxNumExtrema keep the most prominent first.
islocalmin: Where the local minima of data are.
    TF = islocalmin(A)
    [TF, P] = islocalmin(A, dim, 'Name', value, ...)
    * As islocalmax, of -A.
ischange: Where abrupt changes in data begin.
    TF = ischange(A)
    TF = ischange(A, method)
    [TF, S1, S2] = ischange(A, method, dim, 'Threshold', t, 'MaxNumChanges', k, 'SamplePoints', x)
    * method is 'mean' (the default), 'variance' or 'linear'. The data are split where the sum of each segment's squared residuals (about its mean or line; for 'variance', its length times the log of its variance) plus Threshold for each change is least; MaxNumChanges asks instead for the best split with at most k changes. S1 and S2 are each segment's mean and variance, or slope and intercept for 'linear'.
trenddecomp: Trends of data: long-term, seasonal and the remainder.
    [LT, ST, R] = trenddecomp(A)
    [LT, ST, R] = trenddecomp(A, 'ssa', lag)
    [LT, ST, R] = trenddecomp(A, 'stl', period)
    * LT + sum(ST, 2) + R is A. 'ssa' (singular spectrum analysis, the default, with a lag of half the data) finds seasonal trends of each period present, the largest first; 'stl' takes one or more periods and gives a seasonal trend for each.

# ---- more charts --------------------------------------------------------------------------------------------------------------------
xline: Vertical lines across the whole axes.
    xl = xline(x)
    xl = xline(x, LineSpec)
    xl = xline(x, LineSpec, label)
    xl = xline(..., 'LabelVerticalAlignment', 'middle', 'LabelOrientation', 'horizontal', Name, Value)
    xl = xline(ax, ...)
    * x may be several values. The lines reach from the bottom of the axes to the top whatever the limits become, and do not change the limits; xl.Value moves one.
yline: Horizontal lines across the whole axes.
    yl = yline(y)
    yl = yline(y, LineSpec, label, Name, Value)
xregion: Shaded bands across the whole axes, from x1 to x2.
    xr = xregion(x1, x2)
    xr = xregion([x1 x2 x3 x4 ...])
    xr = xregion(..., 'FaceColor', c, 'FaceAlpha', a)
yregion: Shaded bands across the whole axes, from y1 to y2.
    yr = yregion(y1, y2)
    yr = yregion(..., Name, Value)
heatmap: Values as coloured cells, each with its number.
    h = heatmap(cdata)
    h = heatmap(xvalues, yvalues, cdata)
    h = heatmap(tbl, xvar, yvar)
    h = heatmap(tbl, xvar, yvar, 'ColorVariable', cvar, 'ColorMethod', 'mean')
    h = heatmap(..., 'Title', t, 'XLabel', x, 'Colormap', cm, 'ColorLimits', [lo hi], 'CellLabelFormat', '%.2f')
    * From a table: how many rows fall in each pair of groups (or ColorMethod 'mean', 'sum', 'median', 'max', 'min' of ColorVariable). Missing cells are dark grey. Setting a property (h.Title = 'x') draws the chart again.
boxchart: Box charts: the quartiles, whiskers to the farthest values within 1.5 times the box, outliers as markers.
    b = boxchart(ydata)
    b = boxchart(xgroupdata, ydata)
    b = boxchart(..., 'GroupByColor', g, 'Notch', 'on', 'Orientation', 'horizontal', 'BoxFaceColor', c, 'BoxWidth', w, 'MarkerStyle', m)
    * A box for each column of ydata, or for each group of xgroupdata (numbers, or categorical or text for labelled boxes).
swarmchart: A scatter plot with the points of each x spread sideways.
    s = swarmchart(x, y)
    s = swarmchart(x, y, sz, c, 'filled', 'XJitter', 'density', 'XJitterWidth', w)
    * XJitter is 'density' (wider where the points are dense; the default), 'rand' or 'none'.
swarmchart3: A 3-D scatter plot with the points spread in x and y.
    s = swarmchart3(x, y, z, sz, c, 'XJitter', ..., 'YJitter', ...)
piechart: A pie chart, its wedges labelled.
    p = piechart(data)
    p = piechart(data, names)
    p = piechart(tbl, var)
    p = piechart(..., 'LabelStyle', 'namepercent', 'StartAngle', 90, 'Direction', 'clockwise')
    * LabelStyle is 'percent', 'name', 'namepercent', 'data', 'namedata', 'datapercent' or 'none'. A categorical (or a table variable) is counted.
donutchart: A pie chart with a hole.
    d = donutchart(data, names)
    d = donutchart(..., 'InnerRadius', 0.6, 'CenterLabel', s)
stackedplot: Each variable in an axes of its own, stacked, sharing x.
    s = stackedplot(tbl)
    s = stackedplot(tbl, vars)
    s = stackedplot(Y)
    s = stackedplot(X, Y)
    s = stackedplot(..., 'Title', t, 'DisplayLabels', labels, 'XVariable', v)
    * A timetable's row times are x.
plotyy: Two plots with a y axis each.
    [ax, h1, h2] = plotyy(x1, y1, x2, y2)
    [ax, h1, h2] = plotyy(x1, y1, x2, y2, fun)
    [ax, h1, h2] = plotyy(x1, y1, x2, y2, fun1, fun2)
    * fun is 'plot' (the default), 'semilogy' or another plotting function, by name or handle. yyaxis does the same in steps.
polarhistogram: A histogram of angles in polar axes.
    h = polarhistogram(theta)
    h = polarhistogram(theta, nbins)
    h = polarhistogram(theta, edges)
    h = polarhistogram(..., 'BinWidth', w, 'Normalization', 'probability', 'DisplayStyle', 'stairs', 'FaceColor', c)
    * Angles in radians, binned over 0 to 2*pi. h.Values and h.BinCounts give the counts.
binscatter: A scatter plot of many points as bins coloured by how many fall in each.
    h = binscatter(x, y)
    h = binscatter(x, y, N)
    h = binscatter(..., 'XLimits', xl, 'YLimits', yl, 'ShowEmptyBins', 'on')
parallelplot: Parallel coordinates: each row a line across the columns.
    p = parallelplot(data)
    p = parallelplot(tbl)
    p = parallelplot(..., 'GroupData', g, 'CoordinateVariables', vars, 'DataNormalization', 'range')
    * Each coordinate is scaled to its range unless DataNormalization is 'none', 'zscore', 'scale' or 'center'; its lowest and highest values are written at its ends.
scatterhistogram: A scatter plot with the histograms of x and y beside it.
    s = scatterhistogram(x, y)
    s = scatterhistogram(x, y, 'GroupData', g)
    s = scatterhistogram(tbl, xvar, yvar, 'GroupVariable', gvar)
wordcloud: Words drawn at sizes by how often they come (or by sizes given).
    wc = wordcloud(words, sizeData)
    wc = wordcloud(tbl, wordVar, sizeVar)
    wc = wordcloud(str)
    wc = wordcloud(C)
    wc = wordcloud(..., 'MaxDisplayWords', n, 'Color', c, 'HighlightColor', c)
    * Text is split into words and counted (short common words left out); a categorical is counted. The largest tenth are highlighted.
fimplicit3: The surface where f(x, y, z) = 0.
    fs = fimplicit3(f)
    fs = fimplicit3(f, [min max])
    fs = fimplicit3(f, [xmin xmax ymin ymax zmin zmax], 'MeshDensity', n)
    * f takes arrays (use .* and .^); the box is [-5 5] in each direction unless given, sampled 35 times.
tetramesh: Tetrahedra drawn as their faces.
    h = tetramesh(T, X)
    h = tetramesh(T, X, c)
    * T is m-by-4, indices into the points X (n-by-3); each tetrahedron is coloured from the colormap by c (1 to m unless given).
isocaps: The faces that close an isosurface where it meets the volume's edges.
    fvc = isocaps(X, Y, Z, V, isovalue)
    fvc = isocaps(V, isovalue)
    fvc = isocaps(..., 'enclose', 'below', 'whichplane', 'xmin')
    [f, v, c] = isocaps(...)
    isocaps(...)
    * The caps cover the boundary where V is above the value ('above', the default) or below it, coloured by V; with no output they are drawn.
isonormals: The normals of an isosurface at its vertices.
    n = isonormals(X, Y, Z, V, vertices)
    n = isonormals(V, vertices)
    isonormals(..., p)
    isonormals(..., 'negate')
    * From the volume's gradient, pointing to lower values; with a patch p its VertexNormals are set.
smooth3: A volume smoothed.
    W = smooth3(V)
    W = smooth3(V, 'box', size)
    W = smooth3(V, 'gaussian', size, sd)
    * size is odd (3 unless given, or [nx ny nz]); sd 0.65; the edges are replicated.
reducepatch: A patch with fewer faces.
    nfv = reducepatch(p, r)
    nfv = reducepatch(fv, r)
    [nf, nv] = reducepatch(faces, vertices, r)
    reducepatch(p, r)
    * r is the fraction of the faces kept (0.5 unless given) or, above 1, how many. With a patch and no output, the patch itself is reduced.
reducevolume: Every R-th element of a volume.
    [nx, ny, nz, nv] = reducevolume(X, Y, Z, V, [Rx Ry Rz])
    nv = reducevolume(V, R)
subvolume: The part of a volume within limits.
    [Nx, Ny, Nz, Nv] = subvolume(X, Y, Z, V, limits)
    Nv = subvolume(V, limits)
    * limits is [xmin xmax ymin ymax zmin zmax]; NaN leaves a side open.
volumebounds: The extent of a volume's coordinates and values.
    lims = volumebounds(X, Y, Z, V)
    lims = volumebounds(V)
    lims = volumebounds(X, Y, Z, U, V, W)
streamslice: Streamlines spread evenly over a 2-D vector field, with arrows.
    h = streamslice(X, Y, U, V)
    h = streamslice(U, V)
    h = streamslice(..., density)
    h = streamslice(..., 'noarrows')
    [verts, averts] = streamslice(...)
    * density 1 unless given (2: twice as many lines). Slices of 3-D fields are not drawn here.
streamparticles: Markers along streamlines, moved along them.
    h = streamparticles(verts, n)
    h = streamparticles(verts, n, 'Animate', k, 'FrameRate', fps, Name, Value)
    * verts from stream2 or stream3; n markers in all; Animate moves them along k times.

# ---- more functions of data -----------------------------------------------------------------------------------------------------------
mink: The k smallest elements.
    B = mink(A, k)
    B = mink(A, k, dim)
    [B, I] = mink(..., 'ComparisonMethod', 'abs')
    * Smallest first, along the first dimension that is not 1 (or dim); NaN last. I gives where they were.
maxk: The k largest elements.
    B = maxk(A, k)
    [B, I] = maxk(A, k, dim, 'ComparisonMethod', 'abs')
    * Largest first; NaN last.
clip: Values held between a lower and an upper bound.
    C = clip(A, lower, upper)
    * NaN stays NaN; the bounds may be arrays that fit A's size.
allfinite: Whether every element is finite.
    tf = allfinite(A)
anynan: Whether any element is NaN.
    tf = anynan(A)
isuniform: Whether a vector's values are evenly spaced.
    tf = isuniform(v)
    [tf, step] = isuniform(v)
    * To round-off; step is NaN when they are not.
rmoutliers: Data without its outliers.
    B = rmoutliers(A)
    B = rmoutliers(A, method)
    B = rmoutliers(A, movmethod, window)
    [B, TFrm] = rmoutliers(..., dim, 'MinNumOutliers', n, Name, Value)
    * The outliers are isoutlier's (its methods and options); a row of a matrix goes when it has an outlier (or MinNumOutliers of them); dim 2 takes columns away instead.
cbrt: The real cube root.
    y = cbrt(x)
interpft: Resampling by the Fourier transform.
    y = interpft(x, n)
    y = interpft(x, n, dim)
    * x is taken as one period of a periodic signal; n points over the same period.
resize: An array padded or cut to a size.
    B = resize(A, m)
    B = resize(A, m, 'Dimension', dim, 'Pattern', p, 'FillValue', v, 'Side', s)
    * m is a length (along the first dimension that is not 1, or Dimension) or a size. Pattern is 'constant' (FillValue, 0 unless given), 'edge', 'circular', 'flip' or 'reflect'; Side 'trailing' (the default), 'leading' or 'both'. Tables gain missing rows.
paddata: An array padded to a size (never cut).
    B = paddata(A, m, Name, Value)
trimdata: An array cut to a size (never padded).
    B = trimdata(A, m, 'Side', s)
groupcounts: How many rows fall in each group.
    G = groupcounts(T, groupvars)
    [B, BG, BP] = groupcounts(A)
    * A table of the groups (sorted) with GroupCount and Percent; for an array, the counts, the groups and the percentages.
grouptransform: Each group's data transformed.
    G = grouptransform(T, groupvars, method)
    G = grouptransform(T, groupvars, method, datavars, 'ReplaceValues', false)
    * method is 'zscore', 'norm', 'meancenter', 'rescale', 'meanfill', 'linearfill' or a function of a column; ReplaceValues false adds the results as new variables.
groupfilter: The rows of the groups that pass a test.
    G = groupfilter(T, groupvars, method)
    G = groupfilter(T, groupvars, method, datavars)
    * method is a function of a group's column giving true or false for the group (or for each row).
pivot: A table of a statistic for each row and column group.
    P = pivot(T, 'Columns', cvar)
    P = pivot(T, 'Columns', cvar, 'Rows', rvar)
    P = pivot(T, 'Columns', cvar, 'Rows', rvar, 'DataVariable', dvar, 'Method', m)
    * Method is 'count' (without DataVariable, the default), 'sum' (with one), 'mean', 'median', 'max', 'min', 'mode', 'std', 'var', 'none' or a function. A variable for each column group.
topkrows: The k rows that sort first.
    B = topkrows(X, k)
    B = topkrows(X, k, col, direction)
    [B, I] = topkrows(T, k, vars, direction)
    * Largest first ('descend') unless 'ascend'; ties broken by the next columns.
lag: A timetable's data moved later.
    TT2 = lag(TT)
    TT2 = lag(TT, n)
    * By n rows (1 unless given; negative moves earlier); the row times stay, missing values where there is nothing.

# ---- patterns -----------------------------------------------------------------------------------------------------------------------
pattern: Text as a pattern that matches it.
    pat = pattern(text)
    * Patterns join with + and give alternatives with | (or in an array); "a" | "b" is a pattern too. contains, startsWith, endsWith, matches, count, strfind, replace, erase, split, extract, extractBefore, extractAfter, extractBetween, insertBefore and insertAfter take patterns.
digitsPattern: Digits 0 to 9.
    pat = digitsPattern
    pat = digitsPattern(n)
    pat = digitsPattern(min, max)
    * One or more, as many as there are, unless counted.
lettersPattern: Letters.
    pat = lettersPattern
    pat = lettersPattern(n)
    pat = lettersPattern(min, max)
alphanumericsPattern: Letters and digits.
    pat = alphanumericsPattern
    pat = alphanumericsPattern(n)
    pat = alphanumericsPattern(min, max)
whitespacePattern: White space.
    pat = whitespacePattern
    pat = whitespacePattern(n)
    pat = whitespacePattern(min, max)
wildcardPattern: Any characters.
    pat = wildcardPattern
    pat = wildcardPattern(n)
    pat = wildcardPattern(min, max)
    pat = wildcardPattern(..., 'Except', chars)
    * As few as will do unless counted: "a" + wildcardPattern + "z" takes the shortest stretch.
characterListPattern: One of a list (or range) of characters.
    pat = characterListPattern(chars)
    pat = characterListPattern(startChar, endChar)
optionalPattern: A pattern, or nothing.
    pat = optionalPattern(p)
asManyOfPattern: A pattern repeated as many times as it can be.
    pat = asManyOfPattern(p)
    pat = asManyOfPattern(p, min, max)
asFewOfPattern: A pattern repeated as few times as will do.
    pat = asFewOfPattern(p, min, max)
letterBoundary: Where letters start, end, or either.
    pat = letterBoundary
    pat = letterBoundary(type)
digitBoundary: Where digits start, end, or either.
    pat = digitBoundary(type)
alphanumericBoundary: Where letters and digits start, end, or either.
    pat = alphanumericBoundary(type)
whitespaceBoundary: Where white space starts, ends, or either.
    pat = whitespaceBoundary(type)
lineBoundary: The start or end of a line.
    pat = lineBoundary(type)
textBoundary: The start or end of the text.
    pat = textBoundary(type)
lookAheadBoundary: Where a pattern comes next (nothing taken).
    pat = lookAheadBoundary(p)
lookBehindBoundary: Where a pattern comes just before (nothing taken).
    pat = lookBehindBoundary(p)
    * p has a fixed length here.
regexpPattern: A regular expression as a pattern.
    pat = regexpPattern(expr)
caseInsensitivePattern: A pattern matched whatever the case.
    pat = caseInsensitivePattern(p)
caseSensitivePattern: A pattern matched in its own case.
    pat = caseSensitivePattern(p)
namedPattern: A pattern with a name to show it by.
    pat = namedPattern(p, name)
extract: The parts of text that match a pattern.
    newStr = extract(str, pat)
    newStr = extract(str, pos)
    * For one text, a column of the matches; for several, an array when each has one match, else a cell. pos takes characters by position.

# ---- odds and ends --------------------------------------------------------------------------------------------------------------------
symmlq: A symmetric system A*x = b solved by SYMMLQ.
    x = symmlq(A, b)
    [x, flag, relres, iter, resvec] = symmlq(A, b, tol, maxit, M1, M2, x0)
    * A symmetric (positive definite or not), a matrix or a function handle; M1*M2 a symmetric positive definite preconditioner. Outputs as pcg's.
bicgstabl: A system A*x = b solved by BiCGStab(l).
    x = bicgstabl(A, b)
    [x, flag, relres, iter, resvec] = bicgstabl(A, b, tol, maxit, M1, M2, x0)
    * l = 2; any square A; M1*M2 a right preconditioner. Outputs as bicgstab's (iter counts whole steps).
parfeval: A function run for its outputs, kept in a future.
    F = parfeval(fcn, nout, X1, ..., Xm)
    F = parfeval(pool, fcn, nout, ...)
    * fcn runs when parfeval is called; fetchOutputs(F) gives its outputs, F.State and F.Error tell how it went.
parfevalOnAll: A function run once for each worker of the pool.
    F = parfevalOnAll(fcn, nout, X1, ..., Xm)
backgroundPool: The pool parfeval runs in.
    pool = backgroundPool
fetchOutputs: The outputs of futures.
    [B1, ..., Bn] = fetchOutputs(F)
    [B1, ..., Bn] = fetchOutputs(F, 'UniformOutput', false)
    * For several futures each output is put together down them (or in a cell). An error in a future is raised.
fetchNext: The next future not yet read.
    [idx, B1, ..., Bn] = fetchNext(F)
afterEach: A function run on the outputs of each future.
    F2 = afterEach(F, fcn, nout)
afterAll: A function run once on the outputs of all the futures.
    F2 = afterAll(F, fcn, nout)
cancel: Futures stopped.
    cancel(F)
memoize: A function that keeps its results for inputs it has had.
    mf = memoize(fh)
    y = mf(x)
    mf.CacheSize = n
    mf.Enabled = false
    * The last 10 results (CacheSize) are kept; a handle to a named function gives the same memoized function each time.
clearCache: A memoized function's kept results forgotten.
    clearCache(mf)
clearAllMemoizedCaches: Every memoized function's kept results forgotten.
    clearAllMemoizedCaches
stats: How a memoized function has used its kept results.
    s = stats(mf)
timeit: The typical time a function takes.
    t = timeit(f)
    t = timeit(f, numOutputs)
    * f takes no inputs, as @() myfun(x); the median of several runs after one to warm up, in seconds.
setpref: A preference kept from one session to the next.
    setpref(group, pref, value)
    setpref(group, {pref1, pref2}, {value1, value2})
    * Kept in the home folder.
addpref: A preference added (an error if it is there).
    addpref(group, pref, value)
getpref: Preferences kept.
    value = getpref(group, pref)
    value = getpref(group, pref, default)
    s = getpref(group)
    s = getpref
    * With a default, a preference not there yet is set to it.
ispref: Whether a preference (or group) is there.
    tf = ispref(group)
    tf = ispref(group, pref)
rmpref: Preferences taken away.
    rmpref(group)
    rmpref(group, pref)
audioplayer: A player of sound samples.
    player = audioplayer(y, Fs)
    player = audioplayer(y, Fs, nBits)
    player = audioplayer(recorder)
    * y is a column (or a column for each channel), -1 to 1 for floating point. play, playblocking, pause, resume, stop and isplaying control it; player.CurrentSample says where it is.
play: Sound played from a player (or recorder); the program goes on.
    play(player)
    play(player, start)
    play(player, [start stop])
playblocking: Sound played, the program waiting until it ends.
    playblocking(player)
    playblocking(player, [start stop])
isplaying: Whether a player is playing now.
    tf = isplaying(player)
resume: Playing (or recording) again from where pause stopped.
    resume(player)
    resume(recorder)
audiorecorder: A recorder of the microphone.
    recorder = audiorecorder
    recorder = audiorecorder(Fs, nBits, nChannels)
    * 8000 Hz, 8 bits, 1 channel unless given; the browser asks before the page may use the microphone.
record: Recording started; the program goes on.
    record(recorder)
    record(recorder, length)
    * For length seconds, or until stop(recorder).
recordblocking: Recording for a time, the program waiting.
    recordblocking(recorder, length)
getaudiodata: What a recorder has recorded.
    y = getaudiodata(recorder)
    y = getaudiodata(recorder, dataType)
    * A column for each channel; 'double' from -1 to 1 unless 'single', 'int16', 'int8' or 'uint8'.
isrecording: Whether a recorder is recording now.
    tf = isrecording(recorder)
detectImportOptions: How readtable would read a file.
    opts = detectImportOptions(filename)
    opts = detectImportOptions(filename, Name, Value)
    * The variables' names and types, the delimiter (or sheet), where the names and the data are. Change opts (opts.SelectedVariableNames, opts.DataLines, setvartype, setvaropts) and give it to readtable, readmatrix, readcell or readvars.
setvartype: The types variables are read as.
    opts = setvartype(opts, type)
    opts = setvartype(opts, vars, type)
    * double, single, the integer types, logical, char, string, categorical, datetime or duration.
setvaropts: Options of variables to read.
    opts = setvaropts(opts, vars, Name, Value)
    * FillValue (for missing numbers), InputFormat (for datetime) and the like.
getvaropts: A variable's import options.
    vopts = getvaropts(opts, var)
readvars: The columns of a file, a variable each.
    [Var1, ..., VarN] = readvars(filename)
    [Var1, ..., VarN] = readvars(filename, opts)
    [Var1, ..., VarN] = readvars(filename, Name, Value)
xmlread: An XML file as a document object.
    DOMnode = xmlread(filename)
    * Its methods read it: getDocumentElement, getElementsByTagName(name) (a list: getLength, item(k) from 0), getAttribute(name), getTextContent, getNodeName, getChildNodes, getFirstChild, getParentNode, getAttributes, and to change it createElement, createTextNode, setAttribute, appendChild, removeChild, setTextContent.
xmlwrite: A document (or node) written as XML.
    xmlwrite(filename, DOMnode)
    str = xmlwrite(DOMnode)
com.mathworks.xml.XMLUtils.createDocument: A new XML document with its root element.
    docNode = com.mathworks.xml.XMLUtils.createDocument(rootName)
bwmorph: A binary morphological operation.
    BW2 = bwmorph(BW, operation)
    BW2 = bwmorph(BW, operation, n)
    * n times (Inf: until nothing changes): 'clean', 'close', 'dilate', 'erode', 'open', 'fill', 'majority', 'remove', 'skel', 'thin', 'shrink', 'spur', 'endpoints', 'branchpoints', 'bridge', 'diag', 'hbreak', 'tophat' or 'bothat'.
bwboundaries: The boundaries of the objects in a binary image (and of their holes).
    B = bwboundaries(BW)
    [B, L, N, A] = bwboundaries(BW, conn, 'noholes')
    * B{k} is [row col] points, clockwise, the first point again at the end; the objects first (N of them), then the holes. L labels objects and holes, A(i, j) is 1 when boundary i lies in j.

# ---- image processing --------------------------------------------------------------------------------------------------------------
imresize: An image made larger or smaller.
    B = imresize(A, scale)
    B = imresize(A, [rows cols])
    B = imresize(A, [rows NaN])
    B = imresize(..., method)
    B = imresize(..., 'Antialiasing', false)
    * method is 'bicubic' (the default), 'bilinear', 'nearest', 'box', 'triangle', 'lanczos2' or 'lanczos3'. When shrinking, the kernel is widened so that fine detail is averaged rather than lost (antialiasing; not for 'nearest'). NaN for rows or columns keeps the aspect ratio. B has A's class.
imrotate: An image turned counterclockwise.
    B = imrotate(A, angle)
    B = imrotate(A, angle, method)
    B = imrotate(A, angle, method, bbox)
    * method is 'nearest' (the default), 'bilinear' or 'bicubic'; bbox 'loose' (the default: B holds all of the turned image, with zeros around it) or 'crop' (B is A's size, about its centre). Whole quarter turns are exact.
imcrop: The part of an image in a rectangle.
    J = imcrop(A, rect)
    [J, rect] = imcrop(A, rect)
    * rect is [xmin ymin width height] in pixels: J holds the pixels whose centres lie in it (width + 1 columns for whole numbers). Choosing the rectangle with the mouse is not made here.
imtranslate: An image moved.
    B = imtranslate(A, [tx ty])
    B = imtranslate(A, [tx ty], method, 'FillValues', v, 'OutputView', 'full')
    * tx columns to the right and ty rows down; fractions are interpolated ('linear' unless 'nearest' or 'cubic'). Uncovered pixels are FillValues (0); 'full' makes B large enough for all of the moved image.
imfilter: An image filtered by a kernel.
    B = imfilter(A, h)
    B = imfilter(A, h, boundary)
    B = imfilter(A, h, 'conv', 'full', ...)
    * Correlation with h unless 'conv', its centre at floor((size(h) + 1)/2). The edge is padded with zeros, a value, 'symmetric', 'replicate' or 'circular'; 'same' (the default) gives A's size, 'full' the whole result. Each colour plane is filtered alike; B has A's class (integers rounded and saturated).
fspecial: A filter kernel of a common kind.
    h = fspecial('average', hsize)
    h = fspecial('disk', radius)
    h = fspecial('gaussian', hsize, sigma)
    h = fspecial('laplacian', alpha)
    h = fspecial('log', hsize, sigma)
    h = fspecial('motion', len, theta)
    h = fspecial('prewitt')
    h = fspecial('sobel')
    h = fspecial('unsharp', alpha)
    * hsize is a number or [rows cols] (3 for average and gaussian, 5 for log); sigma 0.5; alpha 0.2; the disk's radius 5; motion is len pixels long at theta degrees (9 and 0). prewitt and sobel find horizontal edges (their transposes vertical ones).
imgaussfilt: An image smoothed by a Gaussian.
    B = imgaussfilt(A)
    B = imgaussfilt(A, sigma)
    B = imgaussfilt(A, sigma, 'FilterSize', s, 'Padding', p)
    * sigma is 0.5 unless given (two values for rows and columns); the filter 2*ceil(2*sigma) + 1 wide; the edge 'replicate' unless Padding says otherwise.
medfilt2: Each pixel the median of its neighbourhood.
    B = medfilt2(A)
    B = medfilt2(A, [m n])
    B = medfilt2(A, [m n], padopt)
    * 3-by-3 unless asked; beyond the edge zeros, or 'symmetric' (mirrored), or 'indexed' (1 for double images, 0 otherwise).
edge: The edges of a gray image, as a logical image.
    BW = edge(I)
    BW = edge(I, method)
    BW = edge(I, method, threshold)
    [BW, threshOut] = edge(...)
    BW = edge(I, 'sobel', threshold, direction, 'nothinning')
    BW = edge(I, 'log', threshold, sigma)
    BW = edge(I, 'zerocross', threshold, h)
    BW = edge(I, 'canny', [low high], sigma)
    * method is 'sobel' (the default), 'prewitt', 'roberts', 'log', 'zerocross', 'canny' or 'approxcanny'. Without a threshold one is chosen from the image; threshOut gives it. direction is 'both', 'horizontal' or 'vertical'.
stretchlim: The limits that leave out the darkest and brightest pixels.
    lowhigh = stretchlim(I)
    lowhigh = stretchlim(I, tol)
    * tol is [low high] as fractions of the pixels (0.01 and 0.99 unless given; one number t means [t 1-t]); the limits are from 0 to 1, a column for each colour.
imadjust: Intensities mapped from one range to another.
    J = imadjust(I)
    J = imadjust(I, [low_in high_in])
    J = imadjust(I, [low_in high_in], [low_out high_out])
    J = imadjust(I, [low_in high_in], [low_out high_out], gamma)
    * Values below low_in become low_out, above high_in high_out, between them a curve of the given gamma (1, straight). The limits are from 0 to 1 whatever the class; without them, stretchlim(I) and [0 1].
imhist: The histogram of an image.
    imhist(I)
    imhist(I, n)
    [counts, binLocations] = imhist(I, n)
    * n bins (256 unless given, 2 for logical) spread evenly over the class's range; with no output it is drawn.
histeq: Contrast spread by histogram equalization.
    J = histeq(I)
    J = histeq(I, n)
    [J, T] = histeq(I, n)
    * The intensities mapped through their cumulative distribution to n levels (64 unless given); T is the mapping.
graythresh: The threshold of Otsu's method.
    level = graythresh(I)
    [level, EM] = graythresh(I)
    * level is from 0 to 1, the one that best separates the pixels into two classes; EM (from 0 to 1) tells how well they separate.
imbinarize: A gray image made logical by a threshold.
    BW = imbinarize(I)
    BW = imbinarize(I, T)
    BW = imbinarize(I, 'global')
    * Pixels brighter than Otsu's level (graythresh), or than T: a number from 0 to 1, or an image of levels of I's size. Adaptive (local) thresholds are not made here.
imcomplement: The negative of an image.
    J = imcomplement(I)
    * The class's largest value less I for integers, 1 - I for double and single, ~I for logical.
strel: A flat structuring element for morphology.
    SE = strel('disk', r)
    SE = strel('square', w)
    SE = strel('rectangle', [m n])
    SE = strel('diamond', r)
    SE = strel('line', len, deg)
    SE = strel('octagon', r)
    SE = strel(nhood)
    * SE.Neighborhood is its logical matrix. The disk is the exact disk of radius r (not an approximation by lines).
imdilate: An image dilated: each pixel the largest value under the structuring element.
    J = imdilate(I, SE)
    * SE is a strel or a logical matrix; logical images give logical images.
imerode: An image eroded: each pixel the smallest value under the structuring element.
    J = imerode(I, SE)
imopen: Morphological opening: erosion, then dilation by the same element.
    J = imopen(I, SE)
    * Takes away bright details smaller than the element.
imclose: Morphological closing: dilation, then erosion by the same element.
    J = imclose(I, SE)
    * Fills dark gaps smaller than the element.
imfill: Holes in a binary image filled.
    BW2 = imfill(BW, 'holes')
    BW2 = imfill(BW, locations)
    BW2 = imfill(BW, locations, conn)
    * A hole is background that cannot be reached from the image's edge (4-connected). locations, linear indices or [row col] rows, are points of background flooded from.
bwlabel: The connected components of a binary image, numbered.
    L = bwlabel(BW)
    [L, n] = bwlabel(BW, conn)
    * 8-connected unless conn is 4; the components numbered in the order their first pixel comes down the columns.
bwconncomp: The connected components of a binary image.
    CC = bwconncomp(BW)
    CC = bwconncomp(BW, conn)
    * CC has Connectivity, ImageSize, NumObjects and PixelIdxList (a cell of each component's linear indices).
regionprops: Measurements of the regions of an image.
    stats = regionprops(BW)
    stats = regionprops(L, properties...)
    stats = regionprops(CC, properties...)
    stats = regionprops(L, I, 'MeanIntensity', ...)
    T = regionprops('table', ...)
    * A logical image's regions are its 8-connected components; a numeric one is a label matrix. Properties: Area, Centroid, BoundingBox ('basic', the default), MajorAxisLength, MinorAxisLength, Eccentricity, Orientation, EquivDiameter, Extent, PixelIdxList, PixelList, FilledArea, ConvexArea, Solidity, and with an intensity image MeanIntensity, MaxIntensity, MinIntensity, WeightedCentroid and PixelValues; 'all' gives them all.
imtile: Images side by side in one image.
    out = imtile(images)
    out = imtile(images, 'GridSize', [rows cols], 'BorderSize', b, 'BackgroundColor', c, 'ThumbnailSize', [h w])
    * images is a cell array, an M-by-N-by-1-or-3-by-K array, or an M-by-N-by-K stack of gray images; they fill the grid row by row.
montage: Images side by side, shown.
    montage(images)
    montage(images, 'GridSize', [rows cols], ...)
    h = montage(...)
    * As imtile, drawn with imshow.

# ---- HDF5, structs in files, spreadsheets -------------------------------------------------------------------------------------------
h5create: A new dataset in an HDF5 file (the file made when there is none).
    h5create(filename, ds, size)
    h5create(filename, ds, size, 'Datatype', class, 'ChunkSize', c, 'Deflate', level, 'FillValue', v)
    * Sizes are in the language's order; Inf in size lets that dimension grow (and needs ChunkSize). Datatype is a numeric class or 'string'.
h5write: Data written to an HDF5 dataset.
    h5write(filename, ds, data)
    h5write(filename, ds, data, start, count)
    h5write(filename, ds, data, start, count, stride)
    * The dataset is made first with h5create; start (from 1), count and stride write into a part of it, a dataset that can grow growing as needed.
h5read: An HDF5 dataset, or part of it.
    data = h5read(filename, ds)
    data = h5read(filename, ds, start, count)
    data = h5read(filename, ds, start, count, stride)
    * Dimensions come in the language's order, the reverse of the file's; text comes as a cell of character vectors, compound types as a struct.
h5readatt: An attribute of an HDF5 group or dataset.
    value = h5readatt(filename, loc, attr)
h5writeatt: An attribute written to an HDF5 group or dataset.
    h5writeatt(filename, loc, attr, value)
h5info: What an HDF5 file holds, as a struct.
    info = h5info(filename)
    info = h5info(filename, loc)
    * Groups, Datasets (each with Datatype, Dataspace, ChunkSize, FillValue, Filters, Attributes) and Attributes, sizes in the language's order.
h5disp: What an HDF5 file holds, shown as a tree.
    h5disp(filename)
    h5disp(filename, loc)
readstruct: A struct from an XML or JSON file.
    S = readstruct(filename)
    S = readstruct(filename, 'FileType', 'json')
    S = readstruct(filename, 'StructNodeName', name, 'AttributeSuffix', s, 'ReadAttributes', false)
    * Each child element is a field: text alone becomes a number or a string, attributes are fields ending in Attribute, text beside them the field Text, and repeated elements an array or a struct array.
writestruct: A struct written as XML or JSON.
    writestruct(S, filename)
    writestruct(S, filename, 'FileType', 'json', 'PrettyPrint', false)
    writestruct(S, filename, 'StructNodeName', name, 'AttributeSuffix', s)
    * The root element is 'struct' unless named; arrays become repeated elements and fields ending in Attribute attributes, as readstruct reads them.
xlsread: Numbers, texts and cells of a spreadsheet.
    num = xlsread(filename)
    num = xlsread(filename, sheet)
    num = xlsread(filename, range)
    [num, txt, raw] = xlsread(filename, sheet, range)
    * num is the block holding the numbers (NaN where other cells are), txt the block of texts, raw every cell from A1 to the last used one. sheet is a name or a number; range like 'B2:D10'. .xlsx and .csv files.
xlswrite: A matrix or cell array written into a spreadsheet.
    xlswrite(filename, A)
    xlswrite(filename, A, sheet)
    xlswrite(filename, A, sheet, range)
    * From the range's top-left cell (A1 unless given) of the sheet (the first, or one made with that name). An existing .xlsx file keeps its other sheets and cells; their values are kept, not their formatting or formulas.
xlsfinfo: Whether a file is a spreadsheet, and its sheets.
    [status, sheets] = xlsfinfo(filename)
readtimetable: A timetable from a text or spreadsheet file.
    TT = readtimetable(filename)
    TT = readtimetable(filename, 'RowTimes', var, ...)
    * The first datetime (or duration) column becomes the row times unless RowTimes names one; readtable's options otherwise.
stack: Variables of a table stacked into one.
    S = stack(T, vars)
    S = stack(T, vars, 'NewDataVariableName', name, 'IndexVariableName', name, 'ConstantVariables', cvars)
    * Each row of T gives a row for each stacked variable: the other variables repeated, an indicator (categorical) of which variable, and its value.
unstack: A variable of a table spread into several, one for each value of an indicator.
    W = unstack(S, vars, ivar)
    W = unstack(S, vars, ivar, 'GroupingVariables', gvars, 'AggregationFunction', f, 'NewDataVariableNames', names)
    * A row for each group of the grouping variables (all the others unless given), a variable for each value of ivar; several values in one place are summed (or given to f), none gives a missing value.

# ---- animation and video ---------------------------------------------------------------------------------------------------------------
animatedline: A line to add points to as a program runs.
    an = animatedline
    an = animatedline(x, y)
    an = animatedline(x, y, z)
    an = animatedline(..., 'Color', c, 'MaximumNumPoints', n, ...)
    an = animatedline(ax, ...)
    * Points are added with addpoints and drawn at drawnow; beyond MaximumNumPoints the oldest go. Its Type is 'animatedline'; it takes a line's properties.
addpoints: Points added to an animated line.
    addpoints(an, x, y)
    addpoints(an, x, y, z)
clearpoints: All points taken off an animated line.
    clearpoints(an)
getpoints: The points of an animated line.
    [x, y] = getpoints(an)
    [x, y, z] = getpoints(an)
VideoWriter: A video file to write frame by frame.
    v = VideoWriter(filename)
    v = VideoWriter(filename, profile)
    open(v), writeVideo(v, frame), close(v)
    * profile is 'Motion JPEG AVI' (the default), 'Uncompressed AVI' or 'Grayscale AVI'; set v.FrameRate (30) and v.Quality (75, for JPEG) before open. MPEG-4 and Motion JPEG 2000 files are not written here.
writeVideo: Frames written to an open VideoWriter.
    writeVideo(v, frame)
    writeVideo(v, img)
    writeVideo(v, frames)
    * A frame from getframe, an image (gray or RGB, of any class), or images stacked in the fourth dimension. Every frame has the first one's size.
VideoReader: A video file to read frame by frame.
    v = VideoReader(filename)
    v = VideoReader(filename, 'CurrentTime', t)
    * AVI files (Motion JPEG, uncompressed or 8-bit) and animated GIFs. v.NumFrames, v.FrameRate, v.Duration, v.Width, v.Height; v.CurrentTime is where the next frame is read.
hasFrame: Whether a VideoReader has a frame left.
    tf = hasFrame(v)
readFrame: The next frame of a VideoReader.
    frame = readFrame(v)
    * An m-by-n-by-3 uint8 image; CurrentTime moves on by a frame.
read: Frames of a VideoReader.
    frames = read(v)
    frames = read(v, k)
    frames = read(v, [first last])
    frames = read(v, Inf)
    * Several frames are stacked in the fourth dimension; Inf is the last frame.

# ---- tools of the desktop --------------------------------------------------------------------------------------------------------------
dbstop: A breakpoint set from a command.
    dbstop in file at line
    dbstop in file
    dbstop at line in file
    dbstop if error
    dbstop(s)
    * The program stops before the line (or the first statement of the file) with the K>> prompt; a line with no statement moves to the next one that has one. 'if error' stops where an error is raised (not inside try), in that function's workspace. The Editor shows the breakpoints as if set in its margin; s is what dbstatus gives.
dbclear: Breakpoints taken away.
    dbclear all
    dbclear in file
    dbclear in file at line
    dbclear if error
dbstatus: The breakpoints set.
    dbstatus
    dbstatus file
    s = dbstatus
dbstack: The functions running now, the innermost first.
    dbstack
    [ST, I] = dbstack
    dbstack('-completenames')
    * Each with its line, as links. ST has file, name and line.
checkcode: What the code checker finds in program files.
    checkcode(filename)
    info = checkcode(filename)
    info = checkcode(filename, '-id')
    s = checkcode(filename, '-string')
    checkcode({file1, file2})
    * Syntax errors; in functions, values assigned but never used, inputs never used, outputs never set, and output not suppressed by a semicolon; and a function named unlike its file. Each message has its line and columns; info has message, line and column (and id).
mlint: The code checker (checkcode).
    mlint(filename)
    info = mlint(filename)
clipboard: Text to and from the system's clipboard.
    clipboard('copy', data)
    str = clipboard('paste')
    * Data that is not text is copied as mat2str writes it. The browser may ask whether the page may read the clipboard.
lookfor: Functions whose help has a word in it.
    lookfor topic
    lookfor topic -all
    names = lookfor(topic)
    * Searches the first line of each function's help (and of program files on the path); -all searches all of it.
datetick: An axis's tick labels as dates.
    datetick
    datetick(axis)
    datetick(axis, fmt)
    datetick(..., 'keepticks', 'keeplimits')
    datetick(ax, ...)
    * The axis's values are taken as datenums. Ticks fall on whole years, months, days, hours or minutes as the range suits, the limits widened to them unless 'keeplimits'; 'keepticks' labels the ticks there are. fmt is a datestr format (text or a number).
# ---- graphs and networks ----------------------------------------------------------------------------------------------------------------
graph: An undirected graph: nodes joined by edges, which may have weights.
    G = graph
    G = graph(A)
    G = graph(A, nodenames)
    G = graph(s, t)
    G = graph(s, t, weights)
    G = graph(s, t, weights, numnodes)
    G = graph(s, t, weights, nodenames)
    G = graph(EdgeTable, NodeTable)
    G = graph(..., 'omitselfloops')
    G = graph(A, 'upper')
    * A is a symmetric adjacency matrix (full or sparse): each nonzero A(i, j) above the diagonal (and on it) is an edge, its value the weight; a logical matrix gives edges without weights. 'upper' or 'lower' reads only that triangle.
    * s and t are node numbers or names, an edge from each s(k) to t(k); nodes named for the first time are added. weights is a value for each edge (or one for all).
    * G.Edges is a table of EndNodes (and Weight, and any other variables of the edge table); G.Nodes a table of Name (when the nodes have names) and any other variables. Edges are kept sorted by their end nodes, the smaller first.
digraph: A directed graph: edges that go from one node to another.
    G = digraph(A)
    G = digraph(A, nodenames)
    G = digraph(s, t)
    G = digraph(s, t, weights)
    G = digraph(s, t, weights, numnodes)
    G = digraph(s, t, weights, nodenames)
    G = digraph(EdgeTable, NodeTable)
    G = digraph(..., 'omitselfloops')
    * A(i, j) nonzero is an edge from i to j. Otherwise as graph; edges are kept sorted by their source, then their target.
numnodes: How many nodes a graph has.
    n = numnodes(G)
numedges: How many edges a graph has.
    m = numedges(G)
findnode: The numbers of nodes given by name.
    ids = findnode(G, name)
    ids = findnode(G, names)
    * 0 for a name that is not a node.
findedge: The numbers of the edges between nodes, or the end nodes of edges.
    idx = findedge(G, s, t)
    [s, t] = findedge(G, idx)
    * 0 where s and t are not joined; for a graph, either way round.
degree: How many edges meet each node of a graph.
    d = degree(G)
    d = degree(G, nodes)
    * A self-loop counts twice. For a digraph, indegree plus outdegree.
indegree: How many edges come into each node of a digraph.
    d = indegree(G)
    d = indegree(G, nodes)
outdegree: How many edges leave each node of a digraph.
    d = outdegree(G)
    d = outdegree(G, nodes)
neighbors: The nodes joined to a node.
    N = neighbors(G, node)
    * For a digraph, edges either way; sorted, each once.
successors: The nodes a node of a digraph points to.
    s = successors(G, node)
    [s, eid] = successors(G, node)
predecessors: The nodes of a digraph that point to a node.
    p = predecessors(G, node)
    [p, eid] = predecessors(G, node)
outedges: The edges leaving a node.
    eid = outedges(G, node)
    [eid, nid] = outedges(G, node)
    * For a graph, every edge at the node. nid are the nodes at the other ends.
inedges: The edges coming into a node.
    eid = inedges(G, node)
    [eid, nid] = inedges(G, node)
edgecount: How many edges join two nodes.
    c = edgecount(G, s, t)
adjacency: A graph's adjacency matrix, sparse.
    A = adjacency(G)
    A = adjacency(G, 'weighted')
    A = adjacency(G, weights)
    * A(i, j) is 1 where an edge joins i to j (both ways for a graph); 'weighted' puts the weights there instead (summed over parallel edges), or a weight given for each edge.
incidence: A graph's incidence matrix, sparse: a row for each node, a column for each edge.
    I = incidence(G)
    * -1 at an edge's source (its first end node) and 1 at its target; self-loops give a column of zeros.
ismultigraph: Whether two nodes are joined by more than one edge.
    tf = ismultigraph(G)
addedge: A graph with edges added.
    H = addedge(G, s, t)
    H = addedge(G, s, t, weights)
    H = addedge(G, EdgeTable)
    * Nodes named or numbered past the last are added. Other edge variables are missing for the new edges.
rmedge: A graph with edges taken away.
    H = rmedge(G, s, t)
    H = rmedge(G, idx)
    * rmedge(G, s, t) takes every edge between s and t.
addnode: A graph with nodes added, joined to nothing.
    H = addnode(G, k)
    H = addnode(G, names)
    H = addnode(G, NodeTable)
rmnode: A graph with nodes taken away, and the edges that meet them.
    H = rmnode(G, nodes)
    * The nodes after them are numbered down.
subgraph: The graph of some nodes and the edges among them.
    H = subgraph(G, nodes)
    * nodes are numbers, names or a logical mask; H numbers them in the order given.
reordernodes: A graph with its nodes numbered in another order.
    H = reordernodes(G, order)
    [H, idx] = reordernodes(G, order)
    * order names every node once; idx says where each edge of H was in G.
flipedge: A digraph with edges turned round.
    H = flipedge(G)
    H = flipedge(G, idx)
    H = flipedge(G, s, t)
shortestpath: A shortest path between two nodes.
    P = shortestpath(G, s, t)
    [P, d] = shortestpath(G, s, t)
    [P, d, edgepath] = shortestpath(G, s, t)
    [...] = shortestpath(..., 'Method', m)
    * The path's length is the sum of its weights (the number of its edges without weights, or with 'unweighted'). 'mixed' allows negative weights (on a digraph without a cycle of negative length); 'auto' picks it when some weight is negative. P is empty and d Inf when t cannot be reached.
distances: The lengths of the shortest paths between nodes.
    d = distances(G)
    d = distances(G, s)
    d = distances(G, s, t)
    d = distances(..., 'Method', m)
    * d(i, j) is the length from s(i) to t(j) (all the nodes when not given); Inf where there is no path.
nearest: The nodes within a distance of a node.
    nodeIDs = nearest(G, s, d)
    [nodeIDs, dist] = nearest(G, s, d)
    [...] = nearest(..., 'Direction', 'incoming', 'Method', m)
    * Nearest first; s itself is not among them. A digraph's paths go out of s unless 'incoming'.
shortestpathtree: The tree of shortest paths from a node.
    TR = shortestpathtree(G, s)
    [TR, D] = shortestpathtree(G, s)
    [TR, D, E] = shortestpathtree(G, s)
    * TR is a digraph with an edge into each node that s reaches, from the node before it on a shortest path. D are the distances; E marks the edges of G in the tree.
bfsearch: The nodes in breadth-first order from a node.
    v = bfsearch(G, s)
    v = bfsearch(G, s, 'Restart', true)
    * Neighbours are visited in the order of their numbers. With 'Restart', the search starts again from the first node not reached, until every node is visited.
dfsearch: The nodes in depth-first order from a node.
    v = dfsearch(G, s)
    v = dfsearch(G, s, 'Restart', true)
allpaths: Every path between two nodes that visits no node twice.
    paths = allpaths(G, s, t)
    [paths, edgepaths] = allpaths(G, s, t)
    [...] = allpaths(..., 'MaxNumPaths', n, 'MaxPathLength', L)
    * A cell of node lists (and edge lists); L counts edges.
conncomp: The connected components of a graph.
    bins = conncomp(G)
    [bins, binsizes] = conncomp(G)
    bins = conncomp(G, 'Type', 'weak')
    C = conncomp(G, 'OutputForm', 'cell')
    * bins(i) is the component of node i, components numbered in the order of their first nodes. A digraph's components are strongly connected (each node reaches each other) unless 'weak' (joined when the edges' directions are ignored).
biconncomp: The biconnected components of a graph: the parts no single node's removal splits.
    bins = biconncomp(G)
    [bins, iC] = biconncomp(G)
    * bins(k) is the component of edge k; iC are the cut vertices, nodes whose removal splits a component.
condensation: A digraph's strongly connected components as nodes of a digraph.
    C = condensation(G)
    * Node k of C is the component conncomp numbers k; C has an edge where an edge of G joins two components, and no cycle.
toposort: The nodes of a digraph without cycles in an order that every edge goes forward in.
    order = toposort(G)
    [order, H] = toposort(G)
    * Of the nodes free to come next, the smallest. H is G with its nodes in that order.
isdag: Whether a digraph has no cycle.
    tf = isdag(G)
hascycles: Whether a graph has a cycle.
    tf = hascycles(G)
    * A self-loop is a cycle.
transclosure: The transitive closure of a digraph: an edge from each node to every node it reaches.
    H = transclosure(G)
    * A node on a cycle reaches itself, a self-loop.
transreduction: The transitive reduction of a digraph: the fewest edges that reach as G does.
    H = transreduction(G)
    * Without cycles, H keeps the edges no longer path replaces. Each strongly connected component becomes one cycle through its nodes in order, and between components one edge of G for each edge of the reduced condensation.
minspantree: A minimum spanning tree of a graph.
    T = minspantree(G)
    [T, pred] = minspantree(G)
    [...] = minspantree(G, 'Root', r, 'Type', 'forest')
    * The tree of least total weight joining the nodes that the root reaches; with 'forest', a tree for each component. pred(i) is the node before i in the tree (0 for a root, NaN for a node not reached).
maxflow: The largest flow between two nodes, edge weights being capacities.
    mf = maxflow(G, s, t)
    [mf, GF] = maxflow(G, s, t)
    [mf, GF, cs, ct] = maxflow(G, s, t)
    * GF is a digraph of the flow on each edge; cs and ct are the two sides of a minimum cut, cs holding s. An edge of a graph carries flow either way. Edges without weights have capacity 1.
centrality: How central each node of a graph is.
    C = centrality(G, type)
    C = centrality(G, type, 'Cost', c, 'Importance', w, ...)
    * type is 'degree', 'closeness', 'betweenness', 'pagerank' or 'eigenvector' (a graph); for a digraph also 'indegree', 'outdegree', 'incloseness', 'outcloseness', 'hubs' and 'authorities'.
    * 'Cost' are the edges' lengths for closeness and betweenness (weights are not used for them otherwise); 'Importance' their weights for the others. 'pagerank' also takes 'FollowProbability' (0.85), 'MaxIterations' (100) and 'Tolerance' (1e-4).
    * Closeness of a node that reaches r of the n - 1 others in a total distance D is (r/(n-1))^2/D: 1/D when the graph is connected. PageRank, eigenvector, hubs and authorities sum to 1.
isisomorphic: Whether two graphs are the same but for how their nodes are numbered.
    tf = isisomorphic(G1, G2)
highlight: Nodes or edges of a graph plot drawn apart.
    highlight(h, nodes)
    highlight(h, s, t)
    highlight(h, 'Edges', idx)
    highlight(h, H)
    highlight(..., 'NodeColor', c, 'EdgeColor', c, 'MarkerSize', m, 'LineWidth', w)
    * h is the plot plot(G) gives. Unless colours and sizes are given: red, the markers half as big again, the edges three times as wide. highlight(h, H) marks the nodes and edges of the graph H (a path tree or spanning tree of G).
    * Nodes given with 'EdgeColor' or 'LineWidth' mark the edges joining each node to the next too, so a path from shortestpath is drawn as a path.
labelnode: Labels of nodes in a graph plot.
    labelnode(h, nodes, labels)
labeledge: Labels of edges in a graph plot.
    labeledge(h, s, t, labels)
    labeledge(h, idx, labels)
    * Each label is drawn at the middle of its edge.
layout: A graph plot's nodes placed again.
    layout(h)
    layout(h, method)
    layout(h, 'layered', 'Direction', d, 'Sources', nodes)
    layout(h, 'force', 'Iterations', n)
    * method is 'auto', 'force', 'layered', 'circle' or 'subspace'; 'auto' is 'layered' for a digraph without cycles and 'force' for others.
# ---- unit tests ---------------------------------------------------------------------------------------------------------------------------
runtests: Run tests and give their results.
    results = runtests
    results = runtests(name)
    results = runtests({name1, name2})
    results = runtests(..., 'IncludeSubfolders', true)
    results = runtests(..., 'Name', pattern, 'ProcedureName', pattern)
    results = runtests(..., 'OutputDetail', level)
    * A name is a test file, a folder, or a test class or function on the path, perhaps followed by /test to run one test of it (SampleTest/testSum). Without a name, the tests of the current folder: its test classes, and the function and script files whose names start or end with test.
    * A test class is classdef Name < matlab.unittest.TestCase with methods (Test) blocks; TestMethodSetup and TestMethodTeardown methods run around each test, TestClassSetup and TestClassTeardown once; a test method whose inputs (after testCase) are TestParameter properties (a cell or a struct of values) runs once for each combination of their values.
    * A function-based test file's first function gives tests = functiontests(localfunctions); a script-based one is a script whose %% sections are its tests, the code before the first section run before each.
    * Each test shows a dot as it ends; failures are shown as they happen, and a summary at the end. pattern may hold * and ?; level is 'None', 'Terse', 'Concise' (when not given), 'Detailed' or 'Verbose' (or 0 to 4).
testsuite: The tests runtests would run, as a suite to run later.
    suite = testsuite
    suite = testsuite(name)
    suite = testsuite(..., 'Name', pattern)
    * suite(k) is one test; suite.Name their names; results = run(suite) runs them.
matlab.unittest.TestSuite.fromFile: A test suite from a test file.
    suite = matlab.unittest.TestSuite.fromFile(file)
    * As testsuite(file).
matlab.unittest.TestSuite.fromFolder: A test suite from the test files of a folder.
    suite = matlab.unittest.TestSuite.fromFolder(folder)
    suite = matlab.unittest.TestSuite.fromFolder(folder, 'IncludeSubfolders', true)
matlab.unittest.TestSuite.fromName: A test suite from the names of tests.
    suite = matlab.unittest.TestSuite.fromName('SampleTest/testSum')
matlab.unittest.TestSuite.fromClass: A test suite from a test class.
    suite = matlab.unittest.TestSuite.fromClass('SampleTest')
    * The class is named as text.
functiontests: The tests of a function-based test file.
    tests = functiontests(localfunctions)
    * Its tests are the local functions whose names start or end with test (case ignored), each taking the test case. setupOnce and teardownOnce run once around them all, setup and teardown around each; testCase.TestData is a struct they share, set in setupOnce or setup.
localfunctions: Handles to the local functions of the file it is called in.
    fhs = localfunctions
    * A column cell array; the file's first function is left out.
matlab.unittest.TestCase.forInteractiveUse: A test case for trying its qualifications at the prompt.
    testCase = matlab.unittest.TestCase.forInteractiveUse
    * Each qualification says whether it passed; an assertion or assumption that fails is an error.
matlab.unittest.TestRunner.withTextOutput: A test runner that reports as runtests does.
    runner = matlab.unittest.TestRunner.withTextOutput
    runner = matlab.unittest.TestRunner.withTextOutput('OutputDetail', level)
    * results = runner.run(suite) (or run(runner, suite)).
matlab.unittest.TestRunner.withNoPlugins: A test runner that runs tests silently.
    runner = matlab.unittest.TestRunner.withNoPlugins
    * results = runner.run(suite); the results say what passed.
assertSuccess: An error unless every test passed.
    results = assertSuccess(results)
    * The error names the tests that failed or did not run to the end (an assumption that failed).
addTeardown: Something to do when the test ends.
    addTeardown(testCase, fh)
    addTeardown(testCase, fh, arg1, arg2, ...)
    testCase.addTeardown(fh, ...)
    * fh(args) runs when the test ends, whether it passed or not, the last added first, before the TestMethodTeardown methods (or teardown).
# ---- calling Python -----------------------------------------------------------------------------------------------------------------------
pyrun: Run Python code, and take its variables.
    pyrun(code)
    x = pyrun(code, "x")
    [a, b] = pyrun(code, ["a" "b"])
    x = pyrun(code, "x", "name", value, ...)
    * code is text: a line, or a string array or cell of lines. It runs in Python's __main__, whose variables stay from one pyrun to the next; the name-value pairs are set there first. What Python prints shows in the Command Window.
    * The functions of Python's modules are called as py.module.function(args) (py.math.sqrt(2), py.numpy.linspace(0, 1, pyargs('num', int32(5)))), its builtins as py.name (py.list({1, 2}), py.len(x)); an object's methods and attributes are read with a dot, p.method(args), and p(k) is an item of a list (from 1) or of a dict (by key). The Python is the one PyLAB runs on: in the page, the browser's (Pyodide), with NumPy, SciPy and the modules the page has loaded.
    * Values going to Python: a scalar becomes a float (an int for an integer class, a bool for logical), a vector a 1-D NumPy array and a matrix a 2-D one, [] None, text str (a string array or char matrix a list of them), a cell a tuple, a struct a dict, a function handle a Python function that calls it. Coming back: None is [], bool logical, int int64, float double, str char; anything else stays a Python object, which double, single, the integer classes, logical, cell, char, string, struct and length convert.
pyrunfile: Run a Python file, and take its variables.
    pyrunfile("file.py")
    pyrunfile("file.py arg1 arg2")
    x = pyrunfile(file, "x", "name", value, ...)
    * The file runs in a namespace of its own, as __main__, with sys.argv its name and the words after it. Values cross as for pyrun.
pyenv: The Python that PyLAB runs on.
    pe = pyenv
    * Its Version, Executable, Home, Status and ExecutionMode ('InProcess'). It cannot be changed: PyLAB is a Python program, and the page's Python is the browser's.
pyargs: Keyword arguments for a Python call.
    kw = pyargs('name1', value1, 'name2', value2, ...)
    * Given last: py.numpy.round(x, pyargs('decimals', int32(2))).
# ---- boundary value problems, delays, PDEs, the ode object --------------------------------------------------------------------------------
bvp4c: Solve a boundary value problem y' = f(x, y) on [a, b] with conditions on y(a) and y(b), by a fourth-order collocation.
    sol = bvp4c(odefun, bcfun, solinit)
    sol = bvp4c(odefun, bcfun, solinit, options)
    * odefun(x, y) gives y' as a column; bcfun(ya, yb) gives the residuals of the boundary conditions, zero when they hold. With unknown parameters p (solinit.parameters gives their guess) they are odefun(x, y, p) and bcfun(ya, yb, p), and the conditions are as many as the equations plus the parameters.
    * solinit (from bvpinit) gives the first mesh and a guess of y on it; the mesh is refined until the residual of the solution, relative to 1 + |f|, is within RelTol on each interval (or NMax points are reached: a warning, and the last solution).
    * sol has x, y and yp on the final mesh (and parameters); deval(sol, x) gives y between, [y, yp] = deval(...) y' too. options (bvpset): RelTol (1e-3), AbsTol, NMax, SingularTerm (S, for y' = S*y/x + f with a = 0), FJacobian, Stats ('on'), Vectorized.
bvp5c: Solve a boundary value problem as bvp4c does, by a fifth-order collocation.
    sol = bvp5c(odefun, bcfun, solinit)
    sol = bvp5c(odefun, bcfun, solinit, options)
    * The four-stage Lobatto IIIA collocation: more accurate than bvp4c's on a mesh, for tighter tolerances. Its inputs and its solution are bvp4c's; it takes no SingularTerm.
bvpinit: A first guess for bvp4c and bvp5c.
    solinit = bvpinit(xmesh, yinit)
    solinit = bvpinit(xmesh, yinit, parameters)
    solinit = bvpinit(sol, [anew bnew])
    * xmesh runs from a to b; yinit is a constant column for every point, or a function yinit(x) giving one. bvpinit(sol, [anew bnew]) takes a solution to a longer interval, its end values carried out to the new ends.
bvpxtend: A guess for a longer interval, from a solution.
    solinit = bvpxtend(sol, xnew)
    solinit = bvpxtend(sol, xnew, ynew)
    * xnew lies beyond a or b; y there is the solution's end value carried on by its slope, or ynew.
bvpset: Make or change the options of bvp4c and bvp5c.
    options = bvpset('RelTol', 1e-6, ...)
    options = bvpset(oldopts, 'Name', value, ...)
    * Names: RelTol, AbsTol, SingularTerm, FJacobian, BCJacobian, Stats, NMax, Vectorized.
bvpget: An option of bvp4c and bvp5c.
    v = bvpget(options, 'Name')
    v = bvpget(options, 'Name', default)
dde23: Solve delay differential equations with constant delays.
    sol = dde23(ddefun, lags, history, tspan)
    sol = dde23(ddefun, lags, history, tspan, options)
    * y'(t) = ddefun(t, y, Z), Z(:, j) being y(t - lags(j)); the lags are positive. history is y before tspan(1): a constant column, a function history(t), or the solution of an earlier dde23 run (to carry it on).
    * The steps land on the points where a lag carries the jump at the start forward (sol.discont), as far as three lags on. sol has x, y, yp, stats and, with an Events function ([value, isterminal, direction] = events(t, y, Z)), xe, ye and ie; deval(sol, t) gives y between.
    * options (ddeset): RelTol (1e-3), AbsTol (1e-6), MaxStep, InitialStep, InitialY (y at the start, when it differs from the history), Jumps, Events, Stats.
ddesd: Solve delay differential equations whose delays may depend on t and y.
    sol = ddesd(ddefun, delays, history, tspan)
    sol = ddesd(ddefun, delays, history, tspan, options)
    * delays(t, y) gives the times at which y is taken (each at most t): Z(:, j) is y(d(j)). A vector of constants is taken as lags, as dde23 takes them. Otherwise as dde23, without discontinuity tracking for delays that depend on y.
ddeset: Make or change the options of dde23 and ddesd.
    options = ddeset('RelTol', 1e-6, ...)
    options = ddeset(oldopts, 'Name', value, ...)
    * Names: RelTol, AbsTol, NormControl, Events, InitialStep, MaxStep, OutputFcn, OutputSel, Stats, InitialY, Jumps.
ddeget: An option of dde23 and ddesd.
    v = ddeget(options, 'Name')
    v = ddeget(options, 'Name', default)
pdepe: Solve parabolic and elliptic partial differential equations in one space variable and time.
    sol = pdepe(m, pdefun, icfun, bcfun, xmesh, tspan)
    sol = pdepe(m, pdefun, icfun, bcfun, xmesh, tspan, options)
    [sol, t] = pdepe(...)
    * The equations c(x, t, u, du/dx) .* du/dt = x^-m d/dx(x^m f(x, t, u, du/dx)) + s(x, t, u, du/dx), m 0 (slab), 1 (cylinder) or 2 (sphere); [c, f, s] = pdefun(x, t, u, dudx), each a column with a value for each equation (a zero in c makes that equation elliptic).
    * u0 = icfun(x); [pl, ql, pr, qr] = bcfun(xl, ul, xr, ur, t) gives the boundary conditions p + q .* f = 0 at each end (q = 0: u is held, p = 0). With m > 0 and the mesh starting at 0, the condition there is the symmetry, f = 0.
    * sol(i, j, k) is u(k) at tspan(i) and xmesh(j) (a matrix for one equation); xmesh and tspan have three values or more. options (odeset): RelTol, AbsTol, MaxStep, InitialStep.
pdeval: A pdepe solution between the mesh points.
    uout = pdeval(m, xmesh, ui, xout)
    [uout, duoutdx] = pdeval(m, xmesh, ui, xout)
    * ui = sol(j, :, k): one equation at one time; between mesh points linearly, duoutdx the slope there.
ode: An initial value problem as an object: its function, its start, its solver.
    F = ode
    F = ode(ODEFcn=@(t, y) ..., InitialValue=y0)
    F = ode(..., InitialTime=t0, Parameters=p, Solver=name)
    F.Name = value
    * Properties: ODEFcn (f(t, y), or f(t, y, p) with Parameters), InitialTime (0), InitialValue, Parameters, Jacobian, MassMatrix, NonNegativeVariables, AbsoluteTolerance (1e-6), RelativeTolerance (1e-3), Solver and SolverOptions (an odeset struct); SelectedSolver says which solver Solver means.
    * Solver is 'auto' (ode45, or ode15s with a mass matrix), 'nonstiff' (ode45), 'stiff' (ode15s) or a solver's name. S = solve(F, ...) solves it; solutionFcn(F, t0, tf) gives a function of t.
solutionFcn: The solution of an ode object as a function of time.
    f = solutionFcn(F, t0, tf)
    * y = f(t) gives a column for each time in t, between t0 (the InitialTime) and tf, from the solver's interpolant.
# ---- distances, clustering, reducing dimensions ---------------------------------------------------------------------------------------------
pdist: The distance between each pair of rows of a matrix.
    D = pdist(X)
    D = pdist(X, distance)
    D = pdist(X, 'minkowski', p)
    D = pdist(X, @distfun)
    * D is a row, the pairs in the order (1,2), (1,3), ..., (1,m), (2,3), ...; squareform makes it a matrix. distance is 'euclidean' (unless given), 'squaredeuclidean', 'seuclidean' (each column scaled by its standard deviation, or by the scales given), 'cityblock', 'minkowski' (p 2 unless given), 'chebychev', 'mahalanobis' (by the covariance of X, or the one given), 'cosine', 'correlation', 'spearman', 'hamming' or 'jaccard'.
    * distfun(XI, XJ) takes a row and a matrix and gives a column of distances.
pdist2: The distance from each row of X to each row of Y.
    D = pdist2(X, Y)
    D = pdist2(X, Y, distance, param)
    [D, I] = pdist2(..., 'Smallest', K)
    [D, I] = pdist2(..., 'Largest', K)
    * D(i, j) is the distance from X(i, :) to Y(j, :); the distances as pdist names them. With 'Smallest' (or 'Largest'), the K smallest in each column, smallest first, and I the rows of X they belong to.
squareform: A distance row (from pdist) as a square matrix, or the other way round.
    Z = squareform(y)
    y = squareform(Z)
    Z = squareform(y, 'tomatrix')
    y = squareform(Z, 'tovector')
knnsearch: The nearest neighbours of points.
    Idx = knnsearch(X, Y)
    [Idx, D] = knnsearch(X, Y, 'K', k, 'Distance', distance)
    * For each row of Y, the k rows of X nearest it (1 unless given), nearest first; D their distances. 'P', 'Scale' and 'Cov' give the parameter of 'minkowski', 'seuclidean' and 'mahalanobis'.
rangesearch: The points within a distance of others.
    Idx = rangesearch(X, Y, r)
    [Idx, D] = rangesearch(X, Y, r, 'Distance', distance)
    * Cells, one for each row of Y: the rows of X within r of it, nearest first, and their distances.
kmeans: k clusters of observations, each about its centroid.
    idx = kmeans(X, k)
    [idx, C, sumd, D] = kmeans(X, k)
    [...] = kmeans(..., 'Distance', d, 'Replicates', r, 'MaxIter', m, 'Start', s, 'EmptyAction', a)
    * Lloyd's iterations: each row to its nearest centroid, each centroid to the middle of its rows (the mean for 'sqeuclidean' (unless given) and the cosine and correlation distances, the median for 'cityblock', the majority for 'hamming'). The start is k-means++ ('plus', unless given), 'sample', 'uniform', 'cluster' or a matrix of centroids; with 'Replicates', the run with the least total distance is kept.
    * C has a row for each centroid, sumd each cluster's total distance, D each row's distance to each centroid. Rows with NaN are left out (idx NaN). A cluster that empties takes the row farthest from its centroid ('singleton'), or is dropped ('drop'), or is an error ('error').
kmedoids: k clusters, each about one of its own observations (the medoid).
    idx = kmedoids(X, k)
    [idx, C, sumd, D, midx] = kmedoids(X, k, 'Distance', d, 'Replicates', r)
    * Seeded as k-means++ seeds, each medoid moved to the member nearest the rest, then swaps of a medoid for another row while they lower the total distance. midx are the medoids' rows. The distance is 'sqeuclidean' unless given (any that pdist takes).
linkage: An agglomerative hierarchical cluster tree.
    Z = linkage(X)
    Z = linkage(X, method)
    Z = linkage(X, method, distance)
    Z = linkage(y, method)
    * Each row of Z joins two clusters (Z(i, 1:2), the observations numbered 1 to m and the clusters made m+1, m+2, ...) at the height Z(i, 3). method is 'single' (unless given), 'complete', 'average', 'weighted', 'centroid', 'median' or 'ward' (the last three on Euclidean distances). y is a row of distances, as pdist gives.
cluster: Clusters cut from a linkage tree; or the clusters of a Gaussian mixture.
    T = cluster(Z, 'MaxClust', n)
    T = cluster(Z, 'Cutoff', c)
    T = cluster(Z, 'Cutoff', c, 'Criterion', 'distance')
    T = cluster(Z, ..., 'Depth', d)
    [idx, nlogL, P] = cluster(gm, X)
    * Clusters are numbered in the order of their first observation. 'Cutoff' cuts where the inconsistency coefficient (or the height, with 'distance') exceeds c; 'MaxClust' gives at most n clusters (a column for each n given).
    * cluster(gm, X) puts each row with the component most probable for it; P are the posterior probabilities, nlogL the negative log-likelihood.
clusterdata: Clusters of observations by linkage and cluster in one step.
    T = clusterdata(X, cutoff)
    T = clusterdata(X, 'MaxClust', n, 'Linkage', method, 'Distance', d)
    * clusterdata(X, c): at most c clusters when c is 2 or more, else cut at inconsistency c; single linkage unless named.
cophenet: How well a linkage tree keeps the distances.
    c = cophenet(Z, Y)
    [c, d] = cophenet(Z, Y)
    * c is the correlation of the distances Y (from pdist) with the heights at which the tree joins each pair (d).
inconsistent: The inconsistency of each link of a tree.
    Y = inconsistent(Z)
    Y = inconsistent(Z, d)
    * A row for each link: the mean and standard deviation of the heights of the links within d levels below it (2 unless given), their number, and (its height - the mean)/the standard deviation.
optimalleaforder: The order of a tree's leaves that keeps the nearest together.
    order = optimalleaforder(Z, D)
    * Of the orders the tree allows, the one with the least sum of distances between neighbouring leaves.
dendrogram: A linkage tree drawn.
    dendrogram(Z)
    [H, T, outperm] = dendrogram(Z, P)
    dendrogram(..., 'Orientation', o, 'ColorThreshold', t, 'Labels', names)
    * At most P leaves are drawn (30 unless given; 0 draws all), the lower links folded into them; T says which leaf holds each observation, outperm the leaves from left to right. Orientation is 'top', 'bottom', 'left' or 'right'; with 'ColorThreshold' (or 'default', 0.7 of the greatest height) each cluster below it takes a colour of its own.
dbscan: Clusters of points that have many neighbours (density-based), the rest noise.
    idx = dbscan(X, epsilon, minpts)
    [idx, corepts] = dbscan(X, epsilon, minpts, 'Distance', d)
    idx = dbscan(D, epsilon, minpts, 'Distance', 'precomputed')
    * A core point has minpts points within epsilon (itself among them); a cluster is the core points joined through such neighbours and the points near them. Noise is -1; clusters are numbered as found from the first point on.
spectralcluster: Clusters from the eigenvectors of a similarity graph.
    idx = spectralcluster(X, k)
    [idx, V, D] = spectralcluster(X, k, 'SimilarityGraph', 'knn'|'epsilon', 'NumNeighbors', n, 'Radius', r, 'KernelScale', s, 'LaplacianNormalization', 'randomwalk'|'symmetric'|'none', 'Distance', d)
    * Points joined to their nearest neighbours (ceil(log(n)) unless given), weighted exp(-(d/s)^2); the k eigenvectors of the graph's Laplacian with the smallest eigenvalues (V, D) clustered by kmeans.
gmdistribution: A Gaussian mixture distribution.
    gm = gmdistribution(mu, sigma)
    gm = gmdistribution(mu, sigma, p)
    * mu has a row for each component; sigma is d-by-d-by-k, or d-by-d shared by all, or 1-by-d-by-k or 1-by-d diagonal; p the proportions (equal unless given). pdf(gm, X), random(gm, n), cluster(gm, X), posterior(gm, X) and mahal(gm, X) work on it.
fitgmdist: A Gaussian mixture fitted to data.
    gm = fitgmdist(X, k)
    gm = fitgmdist(X, k, 'CovarianceType', 'full'|'diagonal', 'SharedCovariance', tf, 'RegularizationValue', r, 'Replicates', n, 'Start', s, 'Options', statset('MaxIter', m, 'TolFun', t))
    * The expectation-maximization algorithm from k-means++ starts (or 'randSample', or a column of starting components), until the log-likelihood changes by less than TolFun (1e-6) relatively or MaxIter (100) iterations; the best of the replicates is kept. r is added to each covariance's diagonal. gm keeps NegativeLogLikelihood, AIC, BIC, Converged and NumIterations.
posterior: The probability of each component of a Gaussian mixture, given each observation.
    P = posterior(gm, X)
    [P, nlogL] = posterior(gm, X)
silhouette: How well each point sits in its cluster.
    s = silhouette(X, clust)
    s = silhouette(X, clust, distance)
    silhouette(X, clust)
    * s = (b - a)/max(a, b), a the mean distance to the rest of its cluster, b to the nearest other cluster ('sqEuclidean' unless given); 0 for a point alone in its cluster. Without an output, drawn as bars, cluster by cluster.
evalclusters: The number of clusters a criterion prefers.
    eva = evalclusters(X, clust, criterion)
    eva = evalclusters(X, clust, criterion, 'KList', ks)
    * criterion is 'CalinskiHarabasz' (between- over within-cluster dispersion, largest best), 'DaviesBouldin' (smallest best), 'silhouette' (the mean silhouette, largest best) or 'gap' (against B reference sets uniform over the data's box, largest best). clust is 'kmeans', 'linkage' (Ward), 'gmdistribution' or a matrix with a column of cluster numbers for each solution. eva.OptimalK, eva.CriterionValues, eva.InspectedK, eva.OptimalY.
pca: The principal components of data.
    coeff = pca(X)
    [coeff, score, latent, tsquared, explained, mu] = pca(X)
    [...] = pca(X, 'NumComponents', k, 'Centered', tf, 'Economy', tf, 'Rows', 'complete'|'all', 'Weights', w, 'VariableWeights', vw)
    * By the SVD of the centred data: coeff's columns are the components (each column's largest element made positive), score the data in their terms, latent their variances, explained the percentage each carries, tsquared Hotelling's T^2 of each row, mu the column means. Rows with NaN are left out ('complete'). 'VariableWeights', 'variance' works on standardized variables. Weights are scaled to sum to the number of rows.
pcacov: Principal components of a covariance matrix.
    coeff = pcacov(V)
    [coeff, latent, explained] = pcacov(V)
ppca: Probabilistic principal components, missing values allowed.
    coeff = ppca(Y, k)
    [coeff, score, pcvar, mu, v, S] = ppca(Y, k, 'Options', statset)
    * The model Y = mu + X W' + noise of variance v, fitted by EM, each row using the values it has (NaN is missing). coeff spans W's columns, orthonormal; pcvar are their variances; S holds W, the expected latent values (Xexp), the reconstruction (Recon), NumIter and the negative log-likelihood.
factoran: A factor analysis model by maximum likelihood.
    lambda = factoran(X, m)
    [lambda, psi, T, stats, F] = factoran(X, m)
    [...] = factoran(..., 'Xtype', 'data'|'covariance', 'Nobs', n, 'Rotate', method, 'Scores', 'wls'|'regression')
    * The correlations are modelled as lambda*lambda' + diag(psi): m common factors and each variable's specific variance psi (at least 'Delta', 0.005). The loadings are rotated ('varimax' unless given; 'none') by T. stats has loglike, dfe and, with the number of observations, chisq and p (the test that m factors suffice). F are the factor scores.
rotatefactors: Factor loadings rotated to be simpler.
    B = rotatefactors(A)
    [B, T] = rotatefactors(A, 'Method', m, 'Normalize', tf, 'Reltol', t, 'Maxit', n, 'Coeff', gamma, 'Power', k)
    * 'varimax' (unless given), 'quartimax', 'equamax', 'parsimax' and 'orthomax' (with 'Coeff') turn the axes, keeping them orthogonal (B = A*T); 'promax' then lets them lean (oblique), towards the varimax loadings raised to 'Power' (4). 'Normalize' (on unless given) works on the rows scaled to unit length.
cmdscale: Classical multidimensional scaling.
    Y = cmdscale(D)
    [Y, e] = cmdscale(D, p)
    * Points (rows of Y) whose Euclidean distances are D's when D is Euclidean, and near them otherwise; e are the eigenvalues of the doubly centred -D.^2/2, the columns of Y ordered by them. D is a square matrix or a row from pdist.
mdscale: Points whose distances match dissimilarities as well as can be.
    Y = mdscale(D, p)
    [Y, stress, disparities] = mdscale(D, p, 'Criterion', c, 'Start', s, 'Replicates', r, 'Options', statset)
    * Nonmetric ('stress', unless given, and 'sstress'): the distances fitted to the best monotone transformation of D (the disparities, by isotonic regression); metric ('metricstress', 'metricsstress', 'sammon', 'strain'): to D itself. Kruskal's stress is the square root of the normalized residual sum of squares. Starts from cmdscale (or 'random', or a matrix).
tsne: A t-distributed stochastic neighbour embedding.
    Y = tsne(X)
    [Y, loss] = tsne(X, 'NumDimensions', d, 'Perplexity', p, 'Exaggeration', e, 'LearnRate', r, 'NumPCAComponents', k, 'Distance', dist, 'Standardize', tf, 'Options', statset)
    * Points in d dimensions (2) whose neighbourhoods are as X's: Gaussian affinities with perplexity p (30) against a Student t's, gradient descent with momentum and gains, the affinities exaggerated (4) for the first 99 iterations. Computed exactly (O(n^2)), whatever 'Algorithm' says; loss is the Kullback-Leibler divergence.
procrustes: The turn, scale and shift that fit one set of points to another.
    d = procrustes(X, Y)
    [d, Z, transform] = procrustes(X, Y, 'Scaling', tf, 'Reflection', tf|'best')
    * Z = b*Y*T + c fits X best by least squares; d is the residual sum of squares over X's (centred). transform has T, b and c. 'Reflection' 'best' (unless given) allows a reflection when it fits better.
canoncorr: Canonical correlation analysis.
    [A, B, r] = canoncorr(X, Y)
    [A, B, r, U, V, stats] = canoncorr(X, Y)
    * The combinations U = (X - mean)*A and V = (Y - mean)*B most correlated, each pair r(k), uncorrelated with the others, unit variance. stats has Wilks' lambda and Bartlett's chi-square test (chisq, df1, pChisq) that the correlations from k on are all zero.
barttest: Bartlett's test of how many principal components differ.
    ndim = barttest(X, alpha)
    [ndim, prob, chisquare] = barttest(X, alpha)
    * For k = 0, 1, ..., whether the p - k smallest eigenvalues of the covariance may be equal: chi-square -(n - 1 - (2p + 5)/6 - 2k/3)*(sum(log(l)) - (p - k)*log(mean(l))) with (p - k - 1)(p - k + 2)/2 degrees of freedom; ndim is the first k not rejected at alpha (0.05).
nnmf: Nonnegative matrix factorization.
    [W, H] = nnmf(A, k)
    [W, H, D] = nnmf(A, k, 'Algorithm', 'als'|'mult', 'Replicates', r, 'W0', W0, 'H0', H0, 'Options', statset)
    * A ~ W*H with no negative entries, by alternating least squares (each solution's negatives set to zero) or multiplicative updates, from random starts (or W0, H0). H's rows have unit length; D is the root mean square residual.
mahal: The squared Mahalanobis distance of points from a sample.
    d = mahal(Y, X)
    D = mahal(gm, X)
    * d(i) = (Y(i, :) - mu)*inv(C)*(Y(i, :) - mu)', mu and C the mean and covariance of X's rows. mahal(gm, X) of a Gaussian mixture: a column for each component.
corrcov: The correlation matrix of a covariance matrix.
    R = corrcov(C)
    [R, sigma] = corrcov(C)
# ---- classification and regression ---------------------------------------------------------------------------------------------------------
fitctree: A classification tree.
    Mdl = fitctree(X, Y)
    Mdl = fitctree(Tbl, ResponseVarName)
    Mdl = fitctree(Tbl, formula)
    Mdl = fitctree(..., 'MaxNumSplits', n, 'MinLeafSize', m, 'MinParentSize', p, 'SplitCriterion', 'gdi'|'deviance', 'NumVariablesToSample', k)
    * CART grown level by level: each node with at least MinParentSize observations (10) split where the Gini index (or the deviance) falls most, each child keeping MinLeafSize (1), until MaxNumSplits (n - 1) splits. Y is numbers, logical, text or categorical (ClassNames sorted); X numbers (a table's categorical variables taken by their codes); rows with NaN are left out.
    * Each model keeps its data and takes predict, loss, resubLoss, resubPredict and crossval; view(Mdl) prints a tree's rules. The fit functions also take 'ClassNames', 'Prior', 'Weights', 'PredictorNames', 'ResponseName', and 'CrossVal', 'on', 'KFold', k, 'Holdout', p, 'Leaveout', 'on' or 'CVPartition', c, which give a cross-validated model.
fitrtree: A regression tree.
    Mdl = fitrtree(X, Y)
    Mdl = fitrtree(Tbl, ResponseVarName)
    Mdl = fitrtree(..., 'MaxNumSplits', n, 'MinLeafSize', m, 'MinParentSize', p)
    * CART by the squared error; otherwise as fitctree. Each leaf predicts its mean.
fitcknn: A k-nearest-neighbour classifier.
    Mdl = fitcknn(X, Y)
    Mdl = fitcknn(..., 'NumNeighbors', k, 'Distance', d, 'DistanceWeight', 'equal'|'inverse'|'squaredinverse', 'Exponent', p, 'Standardize', tf)
    * The score of each class is its share of the k nearest training points' votes (1 unless given), weighted as asked; ties go to the first class.
fitcdiscr: Discriminant analysis: classes as multivariate normal distributions.
    Mdl = fitcdiscr(X, Y)
    Mdl = fitcdiscr(..., 'DiscrimType', 'linear'|'quadratic'|'diagLinear'|'diagQuadratic'|'pseudoLinear'|'pseudoQuadratic', 'Gamma', g, 'Prior', p)
    * Linear: one covariance pooled over the classes (n - K degrees of freedom); quadratic: each class its own; diag: their diagonals only; pseudo: a pseudo-inverse when singular. Scores are the posterior probabilities; Mu and Sigma hold the estimates. Gamma shrinks the pooled covariance towards its diagonal.
fitcnb: A naive Bayes classifier.
    Mdl = fitcnb(X, Y)
    Mdl = fitcnb(..., 'DistributionNames', names, 'Width', w, 'Prior', p)
    * Each variable independent within each class: 'normal' (unless given; the mean and the unbiased standard deviation), 'kernel' (a normal kernel density, its width (4/(3n))^(1/5) times the MAD over 0.6745 unless given), 'mvmn' (each value's frequency, plus one) or 'mn' (counts, multinomial). One name for all, or one for each variable.
fitcsvm: A support vector machine for two classes.
    Mdl = fitcsvm(X, Y)
    Mdl = fitcsvm(..., 'KernelFunction', 'linear'|'gaussian'|'polynomial', 'BoxConstraint', C, 'KernelScale', s|'auto', 'PolynomialOrder', q, 'Standardize', tf, 'DeltaGradientTolerance', tol)
    * The dual problem solved by SMO with second-order working-set choice, until the gradient gap is below tol (1e-3). The kernels are x*z', exp(-|x - z|^2) and (1 + x*z')^q on x/s and z/s (s 1 unless given; 'auto' the median distance of 200 sampled points). The score of the second class is the decision value f(x) = sum(alpha*y*K) + Bias, of the first -f(x).
fitrsvm: Support vector regression.
    Mdl = fitrsvm(X, Y)
    Mdl = fitrsvm(..., 'KernelFunction', k, 'BoxConstraint', C, 'Epsilon', e, 'KernelScale', s, 'Standardize', tf)
    * Epsilon-insensitive regression by the same solver; BoxConstraint is iqr(Y)/1.349 and Epsilon iqr(Y)/13.49 unless given.
fitcecoc: Many classes by binary learners and an error-correcting output code.
    Mdl = fitcecoc(X, Y)
    Mdl = fitcecoc(..., 'Learners', t, 'Coding', 'onevsone'|'onevsall'|'binarycomplete'|'ordinal')
    * A binary learner for each column of the coding matrix (CodingMatrix: 1 a positive class, -1 a negative one, 0 left out); learners are 'svm' (unless given), 'linear', 'tree', 'knn', 'discriminant', 'naivebayes' or a template. A class's score is minus the mean binary loss over its columns: the hinge loss on SVM and linear margins, the quadratic loss on the others' probabilities scaled to [-1, 1].
fitcensemble: An ensemble of classification trees.
    Mdl = fitcensemble(X, Y)
    Mdl = fitcensemble(..., 'Method', m, 'NumLearningCycles', n, 'Learners', templateTree(...), 'LearnRate', r)
    * Method 'AdaBoostM1' (two classes; unless given then), 'AdaBoostM2' (more classes; unless given then; boosted here by SAMME, the multiclass AdaBoost of Zhu and others), 'GentleBoost', 'LogitBoost' (two classes) or 'Bag' (random forest: bootstrap samples, sqrt(p) variables tried at each split, full trees). Boosting grows trees of 10 splits unless the template says; n is 100 and r 1 unless given. oobLoss and oobPredict use the bagged trees that did not see each observation.
fitrensemble: An ensemble of regression trees.
    Mdl = fitrensemble(X, Y)
    Mdl = fitrensemble(..., 'Method', 'LSBoost'|'Bag', 'NumLearningCycles', n, 'Learners', templateTree(...), 'LearnRate', r)
    * LSBoost (unless given): each tree fitted to the residuals of those before it; Bag: bootstrap samples, a third of the variables tried at each split, leaves of 5.
fitclinear: A linear classifier for two classes, regularized.
    Mdl = fitclinear(X, Y)
    Mdl = fitclinear(..., 'Learner', 'svm'|'logistic', 'Lambda', l, 'Regularization', 'ridge'|'lasso')
    * Minimizes the mean loss (hinge, or logistic) plus Lambda/2*|Beta|^2 (ridge) or Lambda*|Beta|_1 (lasso; logistic learner only), Lambda 1/n unless given, the Bias free. The SVM by dual coordinate descent, the rest by L-BFGS.
fitrlinear: A linear regression model, regularized.
    Mdl = fitrlinear(X, Y)
    Mdl = fitrlinear(..., 'Learner', 'svm'|'leastsquares', 'Lambda', l, 'Regularization', 'ridge'|'lasso', 'Epsilon', e)
    * 'svm' (unless given) is epsilon-insensitive (Epsilon iqr(Y)/13.49 unless given), by dual coordinate descent; 'leastsquares' half the mean squared error, by L-BFGS.
fitcnet: A feedforward neural network classifier.
    Mdl = fitcnet(X, Y)
    Mdl = fitcnet(..., 'LayerSizes', sizes, 'Activations', 'relu'|'tanh'|'sigmoid'|'none', 'Lambda', l, 'IterationLimit', n, 'Standardize', tf)
    * Fully connected layers (one of 10 unless given), softmax output, cross-entropy plus Lambda/2 times the squared weights, minimized by L-BFGS (1000 iterations at most) from Glorot-uniform weights (drawn from rng's generator) and zero biases.
fitrnet: A feedforward neural network for regression.
    Mdl = fitrnet(X, Y)
    Mdl = fitrnet(..., 'LayerSizes', sizes, 'Activations', a, 'Lambda', l, 'IterationLimit', n, 'Standardize', tf)
    * As fitcnet, a linear output and half the mean squared error.
fitrgp: Gaussian process regression.
    Mdl = fitrgp(X, Y)
    Mdl = fitrgp(..., 'KernelFunction', k, 'BasisFunction', 'constant'|'none'|'linear', 'Sigma', s, 'KernelParameters', theta, 'FitMethod', 'exact'|'none', 'Standardize', tf)
    * Kernels 'squaredexponential' (unless given), 'exponential', 'matern32', 'matern52', 'rationalquadratic', 'ardsquaredexponential'; their length scale(s) and signal sd, and the noise sd Sigma, maximize the marginal likelihood (the basis coefficients Beta by generalized least squares). [ypred, ysd, yint] = predict(Mdl, Xnew, 'Alpha', a): ysd and yint are for new observations, noise included.
fitckernel: A Gaussian-kernel classifier by random features.
    Mdl = fitckernel(X, Y)
    Mdl = fitckernel(..., 'Learner', 'svm'|'logistic', 'NumExpansionDimensions', m, 'KernelScale', s, 'Lambda', l)
    * X mapped to m random Fourier features of the Gaussian kernel (2^ceil(min(log2(p) + 5, 15)) unless given), then a linear classifier as fitclinear fits.
fitrkernel: Gaussian-kernel regression by random features.
    Mdl = fitrkernel(X, Y)
    Mdl = fitrkernel(..., 'Learner', 'svm'|'leastsquares', 'NumExpansionDimensions', m, 'KernelScale', s, 'Lambda', l)
TreeBagger: Bagged decision trees (a random forest).
    B = TreeBagger(n, X, Y)
    B = TreeBagger(n, X, Y, 'Method', 'classification'|'regression', 'NumPredictorsToSample', k, 'MinLeafSize', m)
    * n trees on bootstrap samples, as fitcensemble's 'Bag'; predict gives classes as text (a cell), and scores.
templateTree: A tree's options for ensembles and fitcecoc.
    t = templateTree('MaxNumSplits', n, 'MinLeafSize', m, ...)
templateSVM: An SVM's options for fitcecoc.
    t = templateSVM('KernelFunction', k, 'BoxConstraint', C, ...)
templateKNN: A k-nearest-neighbour learner's options for fitcecoc.
    t = templateKNN('NumNeighbors', k, ...)
templateDiscriminant: A discriminant learner's options for fitcecoc.
    t = templateDiscriminant('DiscrimType', type)
templateNaiveBayes: A naive Bayes learner's options for fitcecoc.
    t = templateNaiveBayes(...)
templateLinear: A linear learner's options for fitcecoc.
    t = templateLinear('Learner', l, 'Lambda', lambda, ...)
templateKernel: A kernel learner's options.
    t = templateKernel('KernelScale', s, ...)
templateGP: A Gaussian process's options.
    t = templateGP('KernelFunction', k, ...)
loss: The loss of a model on data.
    L = loss(Mdl, X, Y)
    L = loss(Mdl, Tbl, ResponseVarName)
    L = loss(..., 'LossFun', f, 'Weights', w)
    * For classification the weighted share misclassified ('classiferror', unless given), or 'hinge', 'logit', 'exponential', 'binodeviance', 'quadratic' (of the margin: the true class's score less the best other's), 'mincost' or 'crossentropy' (of the posterior); for regression the mean squared error ('mse'), or 'epsiloninsensitive'.
resubLoss: The loss of a model on the data it was fitted to.
    L = resubLoss(Mdl)
    L = resubLoss(Mdl, 'LossFun', f)
resubPredict: A model's predictions for the data it was fitted to.
    [label, score] = resubPredict(Mdl)
crossval: Cross-validation of a model, or of a function.
    CVMdl = crossval(Mdl)
    CVMdl = crossval(Mdl, 'KFold', k)
    CVMdl = crossval(Mdl, 'Holdout', p)
    CVMdl = crossval(Mdl, 'Leaveout', 'on')
    CVMdl = crossval(Mdl, 'CVPartition', c)
    vals = crossval(fun, X, Y, 'KFold', k)
    mse = crossval('mse', X, y, 'Predfun', predfun)
    mcr = crossval('mcr', X, y, 'Predfun', predfun)
    * A model is fitted again with its options on each training set (10 folds unless given); kfoldLoss and kfoldPredict use each on the rest. fun(XTRAIN, YTRAIN, XTEST, YTEST) gives a row of values for each fold; predfun(XTRAIN, ytrain, XTEST) gives predictions, and 'mse' (squared error) or 'mcr' (misclassification) is summed over the folds and divided by n. 'Partition', 'Stratify' (a grouping) and 'MCReps' (repetitions) are taken too.
kfoldLoss: The loss of a cross-validated model on the observations each fold left out.
    L = kfoldLoss(CVMdl)
    L = kfoldLoss(CVMdl, 'Mode', 'average'|'individual', 'LossFun', f)
kfoldPredict: Each observation predicted by the fold's model not fitted to it.
    label = kfoldPredict(CVMdl)
    [label, score] = kfoldPredict(CVMdl)
oobLoss: A bagged ensemble's loss on each observation by the trees that did not see it.
    L = oobLoss(Mdl)
oobPredict: A bagged ensemble's out-of-bag predictions.
    [label, score] = oobPredict(Mdl)
compact: A model for predicting only.
    CMdl = compact(Mdl)
    * Here the model itself, which keeps its data.
cvpartition: A partition of observations into training and test sets.
    c = cvpartition(n, 'KFold', k)
    c = cvpartition(group, 'KFold', k)
    c = cvpartition(n, 'HoldOut', p)
    c = cvpartition(n, 'Leaveout')
    c = cvpartition(n, 'Resubstitution')
    c = cvpartition(group, ..., 'Stratify', tf)
    * Random (from rng's generator); with a grouping, each set keeps the groups' proportions (stratified). training(c, i) and test(c, i) give logical columns; c.NumTestSets, c.TrainSize, c.TestSize.
training: The training set of a partition.
    idx = training(c)
    idx = training(c, i)
test: The test set of a partition.
    idx = test(c)
    idx = test(c, i)
repartition: A new random partition like another.
    cnew = repartition(c)
confusionmat: The confusion matrix of known and predicted classes.
    C = confusionmat(group, grouphat)
    [C, order] = confusionmat(group, grouphat, 'Order', order)
    * C(i, j) counts the observations of class i predicted as class j, the classes sorted (or in the order given).
confusionchart: A confusion matrix drawn.
    cm = confusionchart(trueLabels, predictedLabels)
    cm = confusionchart(C)
    cm = confusionchart(C, classLabels)
    cm = confusionchart(..., 'Normalization', n, 'RowSummary', r, 'ColumnSummary', c, 'Title', t)
    * The diagonal blue and the rest red, each cell shaded by its count. Normalization is 'absolute', 'row-normalized', 'column-normalized' or 'total-normalized'; the summaries add the share right in each row or column. cm.NormalizedValues are the values shown.
perfcurve: A classifier's performance as its threshold moves (the ROC curve unless other criteria are named).
    [X, Y] = perfcurve(labels, scores, posclass)
    [X, Y, T, AUC, OPTROCPT] = perfcurve(labels, scores, posclass, 'XCrit', c, 'YCrit', c)
    * For each threshold T (the distinct scores, highest first, from no positive at all), the criteria of the observations scored at least T: 'fpr' and 'tpr' (unless given), 'tnr', 'fnr', 'ppv'/'prec', 'npv', 'reca', 'sens', 'spec', 'fall', 'miss', 'accu', 'tp', 'fn', 'fp', 'tn', 'rpp', 'rnp'. AUC is the area under Y against X (trapezoids); OPTROCPT the ROC point where the slope is N/P.
# ---- more statistics ------------------------------------------------------------------------------------------------------------------------
lasso: Lasso and elastic net regression along a path of penalties.
    B = lasso(X, y)
    [B, FitInfo] = lasso(X, y, 'Alpha', a, 'Lambda', l, 'NumLambda', n, 'LambdaRatio', r, 'CV', k, 'Standardize', tf, 'Weights', w, 'MaxIter', m, 'RelTol', t, 'DFmax', d)
    * For each lambda, the coefficients minimizing 1/(2N) sum (y - b0 - X b)^2 + lambda (Alpha |b|_1 + (1 - Alpha)/2 |b|^2): Alpha 1 (unless given) is the lasso, less is the elastic net. By coordinate descent along the path, each from the last.
    * Without 'Lambda', NumLambda (100) values from the smallest that gives no predictors down by LambdaRatio (1e-4), geometrically. B has a column for each lambda, ascending; FitInfo has Intercept, Lambda, Alpha, DF and MSE, and with 'CV' (folds, or a cvpartition) the cross-validated MSE with SE, LambdaMinMSE, Lambda1SE, IndexMinMSE and Index1SE. X is standardized for the fit unless 'Standardize' is false; the coefficients are given in X's own units.
stepwiselm: A linear model built by adding and removing terms one at a time.
    mdl = stepwiselm(X, y)
    mdl = stepwiselm(X, y, modelspec, 'Upper', spec, 'Lower', spec, 'PEnter', pe, 'PRemove', pr, 'Verbose', v, 'NSteps', n)
    * From modelspec ('constant' unless given, or 'linear' or 'interactions'), the term not in the model with the smallest F-test p-value enters while it is below PEnter (0.05); when none can, the term in it with the largest p-value leaves if above PRemove (0.10); until neither. Terms come from Upper ('interactions' unless given), and an interaction only when its main effects are in; those of Lower always stay. Each step is shown unless 'Verbose' is 0; the result is the fitlm model.
anovan: N-way analysis of variance.
    p = anovan(y, group)
    [p, tbl, stats, terms] = anovan(y, group, 'model', m, 'sstype', s, 'varnames', names, 'display', 'on'|'off')
    * group is a cell of grouping variables (or a matrix, a column for each). model is 'linear' (main effects, unless given), 'interaction' (and the two-way ones), 'full', the highest order, or a matrix of terms (a row each, 1 for each factor in it). sstype 3 (unless given) compares the full model with it less each term, 2 with each term and the terms that do not contain it, 1 adds the terms in turn; the factors are coded to sum to zero. The table is shown unless 'display' is 'off'.
manova1: One-way multivariate analysis of variance.
    d = manova1(X, group)
    [d, p, stats] = manova1(X, group, alpha)
    * d is the dimension of the space the group means span, as far as the data show: the number of Bartlett's chi-square tests of Wilks' lambda rejected in turn at alpha (0.05); p are those tests' p-values. stats has W, B and T (the within-group, between-group and total sums of squares and products), their degrees of freedom, lambda, chisq, chisqdf, the eigenvalues and eigenvectors of W^-1 B, the canonical variables (canon), the Mahalanobis distances of the points (mdist) and of the group means (gmdist).
bootci: A bootstrap confidence interval.
    ci = bootci(nboot, bootfun, d1, d2, ...)
    ci = bootci(nboot, {bootfun, d1, ...}, 'Type', t, 'Alpha', a, 'NBootStd', m)
    [ci, bootstat] = bootci(...)
    * nboot resamples of the data's rows (from rng's generator). Type 'bca' (unless given: the bias-corrected and accelerated percentiles, the acceleration from the jackknife), 'per' (percentiles), 'cper' (bias-corrected), 'norm' (the bootstrap's bias and standard error) or 'stud' (studentized, each resample's standard error from NBootStd (100) more). ci has the lower bounds in its first row.
ansaribradley: The Ansari-Bradley test that two samples have the same dispersion.
    h = ansaribradley(x, y)
    [h, p, stats] = ansaribradley(x, y, 'Alpha', a, 'Tail', 'both'|'right'|'left')
    * Exact for small samples without ties, by the normal approximation otherwise (SciPy's); stats has W, the rank-score statistic of x, and Wstar, its normal score.
copularnd: Random vectors from a copula: uniform marginals, a chosen dependence.
    U = copularnd('Gaussian', rho, n)
    U = copularnd('t', rho, nu, n)
    U = copularnd(family, alpha, n)
    * family is 'Gaussian', 't' (rho a correlation matrix, or a number for two dimensions), or 'Clayton', 'Frank' or 'Gumbel' (two dimensions, parameter alpha).
copulapdf: A copula's density.
    y = copulapdf(family, U, rho)
    y = copulapdf('t', U, rho, nu)
    y = copulapdf(family, U, alpha)
copulacdf: A copula's distribution function.
    y = copulacdf(family, U, rho)
    y = copulacdf('t', U, rho, nu)
    y = copulacdf(family, U, alpha)
copulastat: The rank correlation a copula's parameter gives.
    r = copulastat(family, param)
    r = copulastat(family, param, 'Type', 'kendall'|'spearman')
    * Kendall's tau unless 'spearman': 2/pi*asin(rho) (Gaussian, t), alpha/(alpha + 2) (Clayton), 1 - 1/alpha (Gumbel), and Debye's function for Frank.
copulaparam: The parameter of a copula that gives a Kendall rank correlation.
    param = copulaparam(family, r)
copulafit: A copula fitted to data in the unit square (or cube).
    rho = copulafit('Gaussian', U)
    [rho, nu] = copulafit('t', U)
    alpha = copulafit(family, U)
    * Gaussian: the correlation of the normal scores; t: nu by the profile likelihood; Clayton, Frank and Gumbel: alpha by maximum likelihood.
fullfact: A full factorial design.
    dFF = fullfact(levels)
    * Every combination of the factors' levels, numbered from 1, the first factor changing fastest.
    * At most 2^20 runs are made.
ff2n: A two-level full factorial design.
    dFF2 = ff2n(n)
    * The 2^n rows of 0 and 1, counting in binary.
    * At most 2^20 runs are made.
fracfact: A two-level fractional factorial design.
    dfF = fracfact(gen)
    * gen names the factors as words of letters: single letters are base factors (their full factorial in -1 and 1), longer words their products, as 'a b c abc'; a word starting with - is negated.
    * At most 2^20 runs are made.
bbdesign: A Box-Behnken design.
    dBB = bbdesign(n)
    dBB = bbdesign(n, 'center', nc)
    * For each pair of the n factors, their four corners at -1 and 1 with the rest at 0; then nc centre points (one unless given).
    * At most 2^20 runs are made.
ccdesign: A central composite design.
    dCC = ccdesign(n)
    [dCC, blocks] = ccdesign(n, 'type', 'circumscribed'|'inscribed'|'faced', 'center', nc)
    * The factorial corners at -1 and 1, the axial points at +-alpha with alpha the fourth root of the corners' number (rotatable), and nc centre points (n unless given); 'inscribed' scales all to fit in [-1, 1], 'faced' puts the axial points on the faces.
    * At most 2^20 runs are made.
candgen: A candidate set for a D-optimal design.
    dC = candgen(nfactors, model)
    * The grid of -1 and 1, with 0 too for 'quadratic' and 'purequadratic' models.
    * At most 2^20 runs are made.
candexch: A D-optimal design chosen from candidate rows.
    rlist = candexch(C, nruns)
    rlist = candexch(C, nruns, 'tries', k, 'maxiter', m)
    * C has a row of model terms for each candidate; the rows (repeats allowed) of the most determinant X'X found by exchanging rows one at a time (Fedorov's method) from k random starts.
rowexch: A D-optimal design by row exchanges.
    dRE = rowexch(nfactors, nruns)
    [dRE, X] = rowexch(nfactors, nruns, model, 'tries', k, 'maxiter', m)
    * Rows of candgen's grid exchanged as candexch does, for model 'linear' (unless given), 'interaction', 'quadratic' or 'purequadratic'; X is the design's model matrix.
hmmgenerate: A sequence from a hidden Markov model.
    [seq, states] = hmmgenerate(len, TRANS, EMIS)
    * TRANS(i, j) is the probability of going from state i to j, EMIS(i, k) of emitting symbol k in state i. The model is in state 1 before the first step.
hmmviterbi: The most likely states of a hidden Markov model for a sequence.
    states = hmmviterbi(seq, TRANS, EMIS)
hmmdecode: The posterior state probabilities of a hidden Markov model.
    PSTATES = hmmdecode(seq, TRANS, EMIS)
    [PSTATES, logpseq, FORWARD, BACKWARD, S] = hmmdecode(seq, TRANS, EMIS)
    * PSTATES(i, t) is the probability of state i at step t given the whole sequence; logpseq the log-probability of the sequence; FORWARD and BACKWARD the scaled forward and backward probabilities (a column more than steps, for the start) and S the scales.
hmmestimate: A hidden Markov model's probabilities from a sequence with known states.
    [TRANS, EMIS] = hmmestimate(seq, states)
    [TRANS, EMIS] = hmmestimate(..., 'Pseudoemissions', P, 'Pseudotransitions', T)
hmmtrain: A hidden Markov model's probabilities estimated from sequences.
    [ESTTR, ESTEMIT] = hmmtrain(seq, TRGUESS, EMITGUESS)
    [ESTTR, ESTEMIT, logliks] = hmmtrain(..., 'Algorithm', 'BaumWelch'|'Viterbi', 'Tolerance', t, 'Maxiterations', n, 'Pseudoemissions', P, 'Pseudotransitions', T)
    * Baum-Welch (unless given) or Viterbi training from the guesses, until the probabilities and the log-likelihood change by less than the tolerance (1e-6) or 500 iterations; seq may be a cell of sequences.
coxphfit: Cox proportional hazards regression.
    b = coxphfit(X, T)
    [b, logl, H, stats] = coxphfit(X, T, 'Censoring', c, 'Ties', 'breslow'|'efron', 'Frequency', f, 'Baseline', x0)
    * The coefficients maximize the partial likelihood (Newton's method), ties by Breslow's approximation unless 'efron'. logl is the log partial likelihood; H the cumulative baseline hazard (Breslow's) at x0 (the means of X unless given), a row for each failure time; stats has beta, se, z, p and covb.
relieff: Predictors ranked by ReliefF.
    [idx, weights] = relieff(X, y, k)
    [idx, weights] = relieff(X, y, k, 'method', 'classification'|'regression', 'sigma', s)
    * Each predictor's weight grows by how it differs between a point and its k nearest neighbours of other classes, and falls by how it differs from its own class's (scaled by its range; Manhattan distances); for regression, by how its differences go with the response's. idx ranks the predictors, largest weight first.
fscchi2: Predictors ranked by chi-square tests of independence.
    [idx, scores] = fscchi2(X, Y)
    * Each predictor (numeric ones in up to 10 groups of equal counts) against the response; scores are -log(p).
fscmrmr: Predictors ranked by minimum redundancy, maximum relevance.
    [idx, scores] = fscmrmr(X, Y)
    * First the predictor sharing the most mutual information with the response, then each time the one whose relevance less its mean mutual information with those chosen is largest (numeric predictors in up to 10 groups).
sequentialfs: Predictors chosen one at a time by a cross-validated criterion.
    inmodel = sequentialfs(fun, X, y)
    [inmodel, history] = sequentialfs(fun, X, y, 'cv', k, 'direction', 'forward'|'backward', 'nfeatures', n, 'keepin', idx, 'keepout', idx)
    * fun(XTRAIN, ytrain, XTEST, ytest) gives a loss summed over the test rows; the criterion is its sum over the folds (10 unless 'cv' says, or 'none') over the number of test rows. Forward (unless given) adds the predictor that lowers it most while it falls (or until nfeatures); backward removes. history has In (a row for each step) and Crit.
andrewsplot: Andrews plot: each observation as a curve.
    andrewsplot(X)
    h = andrewsplot(X, 'Group', g, 'Standardize', 'on'|'PCA'|'PCAStd')
    * f(t) = x1/sqrt(2) + x2 sin(2 pi t) + x3 cos(2 pi t) + x4 sin(4 pi t) + ... for t from 0 to 1; a colour (and a line object) for each group.
parallelcoords: Parallel coordinates: each observation as a line across its variables.
    parallelcoords(X)
    h = parallelcoords(X, 'Group', g, 'Labels', names, 'Standardize', 'on'|'PCA'|'PCAStd')
probplot: A probability plot of data against a distribution.
    probplot(y)
    probplot(dist, y)
    h = probplot(...)
    * The sorted data against the distribution's quantiles at (i - 0.5)/n, with the line through their quartiles: 'normal' (unless given), 'exponential', 'extreme value', 'lognormal' and 'weibull' (on log data), 'rayleigh', 'half normal'.
# ---- control systems ----------------------------------------------------------------------------------------------------------------------------
tf: A transfer function model.
    sys = tf(num, den)
    sys = tf(num, den, Ts)
    s = tf('s')
    z = tf('z', Ts)
    sys = tf(M)
    sys = tf(sys)
    sys = tf(..., Name, Value)
    * num and den are coefficients in descending powers; cells of them (a row for each output, a column for each input) make a model with many inputs and outputs. Ts is the sample time (0, continuous, unless given; -1 unspecified). s = tf('s') lets a model be written by arithmetic: (s + 1)/(s^2 + 2*s + 4); exp(-tau*s) is a delay.
    * Models add, subtract, multiply (in series: sys1*sys2 feeds sys2 into sys1), divide, invert (inv), raise to whole powers, transpose, concatenate ([sys1, sys2] side by side, [sys1; sys2] one above another) and index (sys(i, j), outputs then inputs). A result is a state-space model if an operand is, else zero-pole-gain if one is, else a transfer function.
    * Properties: Numerator, Denominator (cells, padded to one length), Variable, Ts, InputDelay, OutputDelay, IODelay, InputName, OutputName, Name, Notes.
zpk: A model as its zeros, poles and gain.
    sys = zpk(z, p, k)
    sys = zpk(z, p, k, Ts)
    s = zpk('s')
    sys = zpk(sys)
    * Shown as products of first-order factors (and second-order ones for complex pairs). Properties Z, P (cells) and K.
ss: A state-space model.
    sys = ss(A, B, C, D)
    sys = ss(A, B, C, D, Ts)
    sys = ss(D)
    sys = ss(sys)
    sys = ss(sys, 'minimal')
    * x' = Ax + Bu, y = Cx + Du (x(k+1) = Ax(k) + Bu(k) in discrete time). A transfer function becomes the controller canonical form of each entry. Properties A, B, C, D, StateName.
pid: A PID controller in parallel form.
    C = pid(Kp, Ki, Kd, Tf)
    C = pid(Kp, Ki, Kd, Tf, Ts)
    * Kp + Ki/s + Kd*s/(Tf*s + 1) (missing gains 0; Tf 0 an ideal derivative); in discrete time Ki*Ts/(z - 1) and Kd/(Tf + Ts/(z - 1)). C.Kp, C.Ki, C.Kd and C.Tf can be read and set; it works as its transfer function everywhere.
feedback: A closed loop.
    sys = feedback(sys1, sys2)
    sys = feedback(sys1, sys2, sign)
    * sys1 in the forward path, sys2 in the feedback path: sys1/(1 + sys2*sys1) for negative feedback (unless sign is +1). For one input and output the polynomials are combined directly, and common factors cancelled.
parallel: Two models side by side, their outputs added.
    sys = parallel(sys1, sys2)
tfdata: The numerators and denominators of a model.
    [num, den] = tfdata(sys)
    [num, den, Ts] = tfdata(sys, 'v')
    * Cells, or rows for a model with one input and output with 'v'; padded with leading zeros to one length.
zpkdata: The zeros, poles and gains of a model.
    [z, p, k] = zpkdata(sys)
    [z, p, k, Ts] = zpkdata(sys, 'v')
ssdata: The state-space matrices of a model.
    [A, B, C, D, Ts] = ssdata(sys)
ss2tf: The transfer function of state-space matrices.
    [b, a] = ss2tf(A, B, C, D)
    [b, a] = ss2tf(A, B, C, D, iu)
tf2ss: State-space matrices of a transfer function.
    [A, B, C, D] = tf2ss(b, a)
    * The controller canonical form.
pole: The poles of a model.
    p = pole(sys)
    * The eigenvalues of A (of a minimal realization, for a transfer function with many inputs and outputs); the denominator's roots for a single-input single-output transfer function.
zero: The zeros of a model.
    z = zero(sys)
    [z, gain] = zero(sys)
    * The numerator's roots of a single-input single-output model (and its gain); the transmission zeros of one with many inputs and outputs.
tzero: The transmission zeros of a model.
    z = tzero(sys)
    * Where the system matrix [A - sI, B; C, D] loses rank: the finite generalized eigenvalues of the pencil (square models).
dcgain: The steady-state gain of a model.
    k = dcgain(sys)
    * H(0) (H(1) in discrete time); Inf where a pole sits there.
evalfr: A model's response at one complex frequency.
    frsp = evalfr(sys, x)
freqresp: A model's frequency response.
    H = freqresp(sys, w)
    [H, wout] = freqresp(sys)
    * H(i, j, k) at the frequency w(k) in rad/s (e^(jw*Ts) in discrete time).
damp: The natural frequencies and damping ratios of a model's poles.
    damp(sys)
    [wn, zeta, p] = damp(sys)
    * zeta = -cos(angle(p)) (of log(p)/Ts in discrete time), in order of frequency; shown with the time constants when nothing is asked for.
isstable: Whether a model is stable.
    tf = isstable(sys)
    * Every pole with a negative real part (inside the unit circle in discrete time).
ctrb: The controllability matrix.
    Co = ctrb(A, B)
    Co = ctrb(sys)
obsv: The observability matrix.
    Ob = obsv(A, C)
    Ob = obsv(sys)
gram: The controllability or observability Gramian.
    Wc = gram(sys, 'c')
    Wo = gram(sys, 'o')
lyap: The continuous Lyapunov or Sylvester equation.
    X = lyap(A, Q)
    X = lyap(A, B, C)
    * A X + X A' + Q = 0; with three matrices A X + X B + C = 0.
dlyap: The discrete Lyapunov equation.
    X = dlyap(A, Q)
    * A X A' - X + Q = 0.
care: The continuous algebraic Riccati equation.
    X = care(A, B, Q)
    [X, L, G] = care(A, B, Q, R, S)
    * The stabilizing X of A'X + XA - (XB + S) R^-1 (B'X + S') + Q = 0; L the closed-loop eigenvalues, G the gain R^-1 (B'X + S').
dare: The discrete algebraic Riccati equation.
    X = dare(A, B, Q)
    [X, L, G] = dare(A, B, Q, R, S)
    * The stabilizing X of A'XA - X - (A'XB + S)(B'XB + R)^-1 (B'XA + S') + Q = 0.
lqr: The linear-quadratic regulator.
    [K, S, P] = lqr(sys, Q, R)
    [K, S, P] = lqr(A, B, Q, R, N)
    * The state feedback u = -Kx minimizing the integral of x'Qx + u'Ru + 2x'Nu; S the Riccati solution, P the closed-loop poles. A discrete model gives the discrete regulator.
dlqr: The discrete linear-quadratic regulator.
    [K, S, e] = dlqr(A, B, Q, R, N)
lqry: The linear-quadratic regulator with output weighting.
    [K, S, e] = lqry(sys, Q, R, N)
lqe: The Kalman estimator gain.
    [L, P, E] = lqe(A, G, C, Q, R, N)
    * For x' = Ax + Bu + Gw, y = Cx + Du + v with noise covariances Q and R (and cross covariance N); P the error covariance, E the estimator's poles.
kalman: The steady-state Kalman filter of a model.
    [kest, L, P] = kalman(sys, Qn, Rn)
    [kest, L, P] = kalman(sys, Qn, Rn, Nn)
    * sys has inputs [u; w], the last size(Qn, 1) of them process noise, and outputs y = Cx + Du + v. kest takes [u; y] and gives [yhat; xhat].
estim: A state estimator from a gain.
    est = estim(sys, L)
    * Input y, outputs [yhat; xhat].
reg: A regulator from a state feedback gain and an estimator gain.
    rsys = reg(sys, K, L)
    * Input y, output u = -K xhat.
place: Pole placement by state feedback.
    K = place(A, B, p)
    * u = -Kx puts the closed-loop poles at p (robust placement, Kautsky, Nichols and Van Dooren; SciPy's place_poles).
acker: Pole placement for a single input by Ackermann's formula.
    k = acker(A, b, p)
covar: The output and state covariances of a model driven by white noise.
    P = covar(sys, W)
    [P, Q] = covar(sys, W)
getPeakGain: The largest gain of a model over frequency.
    gpeak = getPeakGain(sys)
    [gpeak, fpeak] = getPeakGain(sys)
    * The largest singular value of the frequency response: a fine grid around the poles and zeros, each local peak refined.
hinfnorm: The H-infinity norm of a model.
    [ninf, fpeak] = hinfnorm(sys)
    * Inf for an unstable model; as norm(sys, Inf).
c2d: A continuous-time model made discrete.
    sysd = c2d(sysc, Ts)
    sysd = c2d(sysc, Ts, method)
    * method is 'zoh' (unless given: exact for inputs held between samples), 'foh', 'tustin', 'matched' (poles and zeros mapped by exp(s*Ts), the DC gain kept) or 'impulse'. A delay becomes a whole number of samples.
d2c: A discrete-time model made continuous.
    sysc = d2c(sysd)
    sysc = d2c(sysd, 'zoh'|'tustin')
    * 'zoh' by the matrix logarithm; 'tustin' by the inverse of the bilinear map.
pade: The Pade approximation of a delay.
    [num, den] = pade(T, N)
    sys = pade(T, N)
    sysx = pade(sys, N)
    * exp(-sT) as a ratio of polynomials of degree N whose numerator is the denominator at -s; pade(sys, N) replaces a model's delays.
minreal: A minimal realization: what cancels taken out.
    sysr = minreal(sys)
    sysr = minreal(sys, tol)
    * For a transfer function, zeros and poles that coincide (to round-off, or tol) cancel; for a state-space model the states that cannot be controlled or observed are dropped.
ss2ss: A state transformation.
    sysT = ss2ss(sys, T)
    * The model in the states z = Tx.
xperm: The states of a model reordered.
    sysp = xperm(sys, p)
canon: A canonical state-space realization.
    [csys, T] = canon(sys, 'modal')
    [csys, T] = canon(sys, 'companion')
    * 'modal' (unless given): A block diagonal, real 2-by-2 blocks for complex pairs; 'companion': the controllability companion form (one input).
hsvd: The Hankel singular values of a stable model.
    hsv = hsvd(sys)
balreal: The balanced realization of a stable model.
    [sysb, g, T, Ti] = balreal(sys)
    * The realization whose controllability and observability Gramians are both diag(g), g the Hankel singular values.
balred: Model reduction by balanced truncation.
    rsys = balred(sys, r)
    rsys = balred(sys, r, 'Truncate')
    * The states of the smallest Hankel singular values left out, keeping the DC gain (their derivatives set to zero) unless 'Truncate'.
modred: A model with states left out.
    rsys = modred(sys, elim)
    rsys = modred(sys, elim, 'MatchDC'|'Truncate')
step: The step response.
    step(sys)
    step(sys, Tfinal)
    step(sys, t)
    step(sys1, 'r', sys2, 'b--', ...)
    [y, t] = step(sys, ...)
    * Drawn when nothing is asked for (each input's response, each output in turn), a staircase in discrete time. The final time is long enough for the slowest pole to settle (7 time constants, and 6 periods of an oscillation). Delays shift the response.
impulse: The impulse response.
    impulse(sys)
    [y, t] = impulse(sys, Tfinal)
initial: The response to initial conditions.
    initial(sys, x0)
    [y, t, x] = initial(sys, x0, Tfinal)
stepplot: The step response drawn.
    stepplot(sys, ...)
impulseplot: The impulse response drawn.
    impulseplot(sys, ...)
lsim: The response to any input.
    lsim(sys, u, t)
    [y, t, x] = lsim(sys, u, t, x0, method)
    * u has a column for each input and a row for each time; between samples it is linear ('foh', unless 'zoh'); the solution is exact for that (the matrix exponential).
stepinfo: The characteristics of a step response.
    S = stepinfo(sys)
    S = stepinfo(y, t)
    S = stepinfo(y, t, yfinal, 'SettlingTimeThreshold', s, 'RiseTimeLimits', [lo hi])
    * RiseTime (from 10% to 90% of the change, unless given), SettlingTime (when the response stays within 2% of the change of its final value), SettlingMin, SettlingMax, Overshoot and Undershoot (percent), Peak and PeakTime (between samples by a parabola).
bode: The frequency response as gain and phase.
    bode(sys)
    bode(sys, w)
    bode(sys, {wmin, wmax})
    bode(sys1, sys2, ...)
    [mag, phase, wout] = bode(sys, ...)
    * mag absolute and phase in degrees (unwrapped); drawn as gain in dB and phase over a logarithmic frequency axis (rad/s) when nothing is asked for. The frequencies span two decades beyond the poles and zeros unless given.
bodeplot: The Bode diagram drawn.
    bodeplot(sys, ...)
nyquist: The Nyquist diagram.
    nyquist(sys)
    [re, im, wout] = nyquist(sys, w)
    * The frequency response in the complex plane, with its mirror image for negative frequencies (dashed) and the critical point -1 when drawn.
nichols: The Nichols chart.
    nichols(sys)
    [mag, phase, wout] = nichols(sys, w)
sigma: The singular values of the frequency response.
    sigma(sys)
    [sv, wout] = sigma(sys, w)
margin: The gain and phase margins of a loop.
    margin(sys)
    [Gm, Pm, Wcg, Wcp] = margin(sys)
    * Gm (absolute) at the frequency Wcg where the phase crosses -180 degrees, Pm (degrees) at Wcp where the gain crosses 1; of several crossings the smallest margins; Inf when there is none. Drawn on the Bode diagram, the margins in its title, when nothing is asked for.
allmargin: Every stability margin of a loop.
    S = allmargin(sys)
    * GainMargin and GMFrequency, PhaseMargin and PMFrequency, DelayMargin (phase margin over crossover frequency, in samples in discrete time) and DMFrequency, and whether the closed loop is Stable.
rlocus: The root locus.
    rlocus(sys)
    [r, k] = rlocus(sys)
    r = rlocus(sys, k)
    * The poles of the closed loop with gain k in negative feedback, as k grows (a column for each gain), branches followed from one gain to the next; drawn with the open-loop poles (x) and zeros (o).
pzmap: The poles and zeros drawn.
    pzmap(sys)
    [p, z] = pzmap(sys)
# ---- global optimization --------------------------------------------------------------------------------------------------------------------
ga: A minimum by a genetic algorithm.
    x = ga(fun, nvars)
    x = ga(fun, nvars, A, b, Aeq, beq, lb, ub, nonlcon, intcon, options)
    [x, fval, exitflag, output, population, scores] = ga(...)
    * fun takes a row of nvars values. Each generation keeps EliteCount of the best, makes CrossoverFraction (0.8) of the rest by scattered crossover of parents chosen by stochastic uniform selection on rank-scaled fitness, and the remainder by Gaussian mutation whose scale shrinks to nothing by the last generation; children are kept within the bounds and integer variables (intcon) rounded. Constraints rank infeasible points after all feasible ones, by their violation (Deb's rule), rather than by MATLAB-style penalties or augmented Lagrangians.
    * Stops after MaxGenerations (100*nvars), when the best value changes relatively by no more than FunctionTolerance over MaxStallGenerations (50), at FitnessLimit, or after MaxTime. PopulationSize is 50 (more than five variables: 200). HybridFcn ('fminsearch', 'fminunc', 'fmincon', 'patternsearch') polishes the answer. Draws from rng's generator.
    * exitflag: 1 stalled within FunctionTolerance, 0 MaxGenerations, 5 FitnessLimit, -2 no feasible point, -5 MaxTime.
particleswarm: A minimum within bounds by a particle swarm.
    x = particleswarm(fun, nvars)
    [x, fval, exitflag, output] = particleswarm(fun, nvars, lb, ub, options)
    * SwarmSize (min(100, 10*nvars)) particles start uniformly within the bounds (or InitialSwarmSpan about 0); each moves by W*v + SelfAdjustmentWeight*u1.*(own best - x) + SocialAdjustmentWeight*u2.*(best of a random neighbourhood - x). A stall counter falls with each improvement of the best and grows otherwise; the inertia W doubles while it is below 2 and halves once it passes 5 (within InertiaRange, [0.1 1.1]), and the neighbourhood grows while the best stalls.
    * Stops when the best changes relatively by no more than FunctionTolerance over MaxStallIterations (20), at ObjectiveLimit, or after MaxIterations (200*nvars). exitflag 1, 0, or -3 (ObjectiveLimit).
simulannealbnd: A minimum within bounds by simulated annealing.
    x = simulannealbnd(fun, x0)
    [x, fval, exitflag, output] = simulannealbnd(fun, x0, lb, ub, options)
    * Each step goes a distance equal to the temperature (InitialTemperature 100, times 0.95 each step) in a random direction (a coordinate leaving the bounds is drawn again within them); a worse point is taken with probability 1/(1 + exp(delta/T)). The temperature starts again every ReannealInterval accepted points. Stops when the best changes by no more than FunctionTolerance over MaxStallIterations (500*nvars), at MaxFunctionEvaluations (3000*nvars), or at ObjectiveLimit (exitflag 5).
patternsearch: A minimum by a generalized pattern search.
    x = patternsearch(fun, x0)
    x = patternsearch(fun, x0, A, b, Aeq, beq, lb, ub, nonlcon, options)
    [x, fval, exitflag, output] = patternsearch(...)
    * Polls x +- mesh size along each coordinate (opportunistically, unless UseCompletePoll): a better point is taken and the mesh multiplied by MeshExpansionFactor (2), else it is multiplied by MeshContractionFactor (0.5); the bounds are never left. Linear and nonlinear constraints by an augmented Lagrangian (Powell, Hestenes, Rockafellar), its subproblems searched to ever finer meshes. Stops when the mesh is below MeshTolerance (1e-6) with the constraints met (exitflag 1), or at MaxIterations or MaxFunctionEvaluations (0).
surrogateopt: A minimum of an expensive function within bounds, by a surrogate.
    x = surrogateopt(fun, lb, ub)
    [x, fval, exitflag, output] = surrogateopt(fun, lb, ub, intcon, options)
    * MinSurrogatePoints (max(20, 2*nvars)) random points first; then each new point is the candidate (about the best point, or every fourth time anywhere in the box) that best weighs a cubic radial basis interpolant's value against the distance to the points so far, the weight cycling; the search radius halves after three failures in a row. MaxFunctionEvaluations is 200. The bounds are finite.
gamultiobj: Points on the Pareto front of several objectives.
    x = gamultiobj(fun, nvars)
    [x, fval, exitflag, output, population, scores] = gamultiobj(fun, nvars, A, b, Aeq, beq, lb, ub, nonlcon, options)
    * fun gives a row of objectives. A genetic algorithm in the manner of NSGA-II: tournaments by nondominated rank and crowding distance, intermediate crossover and Gaussian mutation, the next population the best fronts (the first held to ParetoFraction, 0.35, of it when it is larger), until MaxGenerations (200*nvars). x and fval are the final nondominated points.
createOptimProblem: An optimization problem for MultiStart and GlobalSearch.
    problem = createOptimProblem(solverName, 'objective', fun, 'x0', x0, Name, Value, ...)
    * solverName is 'fmincon', 'fminunc', 'lsqnonlin', 'lsqcurvefit' or 'fminsearch'; the fields are objective, x0, Aineq, bineq, Aeq, beq, lb, ub, nonlcon, options, xdata and ydata. The solver itself takes it too (fmincon(problem)).
MultiStart: A local solver run from many start points.
    ms = MultiStart
    ms = MultiStart('Name', value, ...)
    [x, fval, exitflag, output, solutions] = run(ms, problem, k)
    * k start points: x0 and k - 1 drawn uniformly within the bounds (1000 either side of x0 where there are none), or the rows of a matrix. solutions are the distinct local minima (within FunctionTolerance and XTolerance), best first, each with X, Fval, Exitflag, Output and the start points X0 that led to it.
GlobalSearch: A local solver run from the best of many trial points.
    gs = GlobalSearch
    gs = GlobalSearch('Name', value, ...)
    [x, fval, exitflag, output, solutions] = run(gs, problem)
    * NumTrialPoints (1000) points are drawn within the bounds and scored by the objective; the local solver runs from x0 and then from the best NumStageOnePoints (200) of them, skipping a point inside the basin of a solution already found (BasinRadiusFactor times the distance the solver moved to reach it). PyLAB's own scheme, simpler than scatter search.
# ---- wavelets ----------------------------------------------------------------------------------------------------------------------------------
wfilters: The four filters of a wavelet.
    [LoD, HiD, LoR, HiR] = wfilters(wname)
    [F1, F2] = wfilters(wname, type)
    * The decomposition and reconstruction lowpass and highpass filters, rows. type 'd' gives LoD and HiD, 'r' LoR and HiR, 'l' the two lowpass ones, 'h' the two highpass ones.
    * Wavelets: haar, db1 to db45 (Daubechies, minimum phase), sym2 to sym20 (symlets), coif1 to coif5 (coiflets), bior1.1, 1.3, 1.5, 2.2, 2.4, 2.6, 2.8, 3.1, 3.3, 3.5, 3.7, 3.9, 4.4, 5.5, 6.8 and rbio with the same numbers (the biorthogonal ones reversed). They are computed: the roots of the Daubechies polynomial to 60 digits for db and sym (which root of each pair a symlet takes follows the standard table), Newton's method on the moment and orthogonality equations for the coiflets, exact fractions for the spline biorthogonal ones.
    * LoR sums to sqrt(2); LoD is LoR reversed for an orthogonal wavelet; HiR(k) = (-1)^k LoD(k) and HiD(k) = (-1)^(k+1) LoR(k), k from 0. The shorter biorthogonal filter is padded with zeros to the even length of the longer.
dbwavf: The scaling filter of a Daubechies wavelet.
    F = dbwavf(wname)
    * LoR/sqrt(2), summing to 1. wname is 'db1' to 'db45' (or 'haar').
symwavf: The scaling filter of a symlet.
    F = symwavf(wname)
    * LoR/sqrt(2), summing to 1. wname is 'sym2' to 'sym20'.
coifwavf: The scaling filter of a coiflet.
    F = coifwavf(wname)
    * LoR/sqrt(2), summing to 1. wname is 'coif1' to 'coif5'.
qmf: The quadrature mirror filter.
    Y = qmf(X)
    Y = qmf(X, P)
    * X reversed, with the signs of its second, fourth, ... elements changed (P even, the default), or of the first, third, ... (P odd).
orthfilt: The four filters of an orthogonal scaling filter.
    [LoD, HiD, LoR, HiR] = orthfilt(W)
    * LoR = W/norm(W), LoD its reverse, the highpass ones as wfilters makes them.
biorfilt: The four filters of a biorthogonal pair.
    [LoD, HiD, LoR, HiR] = biorfilt(DF, RF)
    * DF and RF, the decomposition and reconstruction scaling filters, are scaled to sum sqrt(2) and padded to one even length (an odd-length RF placed one sample before DF's middle), as wfilters gives the bior wavelets.
dwtmode: The extension mode of the discrete transforms.
    dwtmode(mode)
    dwtmode(mode, 'nodisp')
    m = dwtmode('status')
    * How a signal is extended past its ends: 'sym' (symmetric, half-point: the default), 'symw' (whole-point), 'asym' and 'asymw' (antisymmetric), 'zpd' (zeros), 'sp0' (the end values), 'sp1' (straight lines through the last two values), 'ppd' (periodic) and 'per' (periodization: half as many coefficients, rounded up, an odd signal first extended by its last value).
    * The mode holds for dwt, idwt, wavedec, waverec, appcoef, wrcoef, dwt2 and the rest until changed; each also takes 'mode', m for one call.
wmaxlev: The largest useful decomposition level.
    L = wmaxlev(sz, wname)
    * floor(log2(n/(lf - 1))), n the smallest of the sizes sz and lf the length of the filters (0 when the signal is shorter than lf - 1): beyond it every coefficient feels the extension.
dwt: One level of the discrete wavelet transform.
    [cA, cD] = dwt(x, wname)
    [cA, cD] = dwt(x, LoD, HiD)
    [cA, cD] = dwt(..., 'mode', m)
    * x extended past its ends by the mode (dwtmode), filtered by LoD and HiD and every second sample kept: floor((n + lf - 1)/2) coefficients each, ceil(n/2) in mode 'per'. Rows from a row, columns from a column.
idwt: One level of the inverse discrete wavelet transform.
    x = idwt(cA, cD, wname)
    x = idwt(cA, cD, LoR, HiR)
    x = idwt(cA, cD, wname, L)
    x = idwt(..., 'mode', m)
    * cA and cD upsampled, filtered by LoR and HiR and added: 2*n - lf + 2 samples (2*n in mode 'per'), or the middle L of them. Either of cA and cD may be [] for zeros.
wavedec: A multilevel wavelet decomposition.
    [c, l] = wavedec(x, n, wname)
    [c, l] = wavedec(x, n, LoD, HiD)
    * dwt n times on the approximations: c = [cA_n, cD_n, ..., cD_1] and l = [length(cA_n), length(cD_n), ..., length(cD_1), length(x)]. Rows, or columns when x is a column; 'mode', m as in dwt.
waverec: The signal from a wavelet decomposition.
    x = waverec(c, l, wname)
    x = waverec(c, l, LoR, HiR)
    * idwt level by level, each result cut to the length l holds for it. waverec(wavedec(x, n, w), w) is x again, to rounding.
appcoef: The approximation coefficients of a decomposition at a level.
    A = appcoef(c, l, wname)
    A = appcoef(c, l, wname, n)
    A = appcoef(c, l, LoR, HiR, n)
    * cA_n, reconstructed from the deepest approximation and the details below level n; n is the deepest level by default, 0 gives the signal.
detcoef: The detail coefficients of a decomposition.
    D = detcoef(c, l)
    D = detcoef(c, l, n)
    [D1, ..., Dp] = detcoef(c, l, [n1, ..., np])
    D = detcoef(c, l, 'cells')
    * cD_n (level 1 by default). Several levels give a cell, or an output each; 'cells' gives every level, level 1 first.
wrcoef: The part of a signal from one level of its decomposition.
    X = wrcoef('a', c, l, wname, n)
    X = wrcoef('d', c, l, wname, n)
    X = wrcoef(type, c, l, LoR, HiR, n)
    * waverec with every other coefficient set to zero: 'a' keeps the approximation at level n, 'd' the details of level n. wrcoef('a', c, l, w, n) plus wrcoef('d', c, l, w, k) for k = 1..n is the signal. n is the deepest level by default.
upcoef: Coefficients reconstructed straight up.
    Y = upcoef(type, x, wname, n)
    Y = upcoef(type, x, wname, n, lx)
    Y = upcoef(type, x, LoR, HiR, n, lx)
    * x upsampled and filtered by LoR ('a') or HiR ('d') once and by LoR n - 1 more times (n is 1 by default), each step in full (2*m + lf - 2 samples); lx keeps the middle lx samples.
wenergy: The share of energy in each part of a decomposition.
    [Ea, Ed] = wenergy(c, l)
    * Percentages of sum(c.^2): Ea in the approximation, Ed(k) in the details of level k.
dwt2: One level of the discrete wavelet transform of an image.
    [cA, cH, cV, cD] = dwt2(X, wname)
    [cA, cH, cV, cD] = dwt2(X, LoD, HiD)
    [cA, cH, cV, cD] = dwt2(..., 'mode', m)
    * dwt along the rows and then down the columns: cA lowpass both ways, cH (horizontal details) highpass down the columns, cV (vertical) highpass along the rows, cD (diagonal) highpass both ways.
idwt2: One level of the inverse transform of an image.
    X = idwt2(cA, cH, cV, cD, wname)
    X = idwt2(cA, cH, cV, cD, LoR, HiR)
    X = idwt2(..., S)
    * S keeps the middle S(1)-by-S(2) part. Any of the four may be [] for zeros.
wavedec2: A multilevel wavelet decomposition of an image.
    [C, S] = wavedec2(X, n, wname)
    [C, S] = wavedec2(X, n, LoD, HiD)
    * C = [A_n(:)' H_n(:)' V_n(:)' D_n(:)' H_(n-1)(:)' ... D_1(:)'], a row; S has the sizes of A_n, of the details of level n, ..., of level 1, and of X, one row each.
waverec2: The image from a wavelet decomposition.
    X = waverec2(C, S, wname)
    X = waverec2(C, S, LoR, HiR)
appcoef2: The approximation of an image's decomposition at a level.
    A = appcoef2(C, S, wname)
    A = appcoef2(C, S, wname, n)
    A = appcoef2(C, S, LoR, HiR, n)
detcoef2: The details of an image's decomposition at a level.
    D = detcoef2(type, C, S, n)
    [H, V, D] = detcoef2('all', C, S, n)
    * type 'h', 'v' or 'd' for one kind; 'c' (compact) gives all three as one row [H(:)' V(:)' D(:)'].
wrcoef2: The part of an image from one kind of coefficient at a level.
    X = wrcoef2(type, C, S, wname, n)
    X = wrcoef2(type, C, S, LoR, HiR, n)
    * type 'a', 'h', 'v' or 'd'; waverec2 with every other coefficient set to zero.
swt: The stationary (undecimated) wavelet transform.
    [swa, swd] = swt(x, n, wname)
    [swa, swd] = swt(x, n, LoD, HiD)
    swc = swt(x, n, wname)
    * Row k of swa and swd holds the approximations and details of level k, as long as x: the filters, with 2^(k-1) - 1 zeros between their taps, applied periodically and nothing dropped. The length of x must be a multiple of 2^n. swc is [swd; swa(n, :)].
iswt: The inverse stationary wavelet transform.
    x = iswt(swa, swd, wname)
    x = iswt(swc, wname)
    x = iswt(..., LoR, HiR)
    * Each level the average of the two inverses its coefficients allow; only the last row of swa is needed.
swt2: The stationary wavelet transform of an image.
    [A, H, V, D] = swt2(X, n, wname)
    swc = swt2(X, n, wname)
    * Page k of each holds level k. Both sizes of X must be multiples of 2^n. swc = cat(3, H, V, D, A(:, :, n)).
iswt2: The inverse stationary wavelet transform of an image.
    X = iswt2(A, H, V, D, wname)
    X = iswt2(swc, wname)
modwt: The maximal overlap discrete wavelet transform.
    w = modwt(x)
    w = modwt(x, wname, J)
    w = modwt(x, LoR, HiR, J)
    w = modwt(..., 'reflection')
    * Rows W_1, ..., W_J and V_J, each as long as x: circular filtering by the reconstruction filters divided by sqrt(2), with 2^(j-1) - 1 zeros between the taps at level j (Percival and Walden's definition), computed by FFT. sum(w(:).^2) is sum(x.^2).
    * The wavelet is 'sym4' and J is floor(log2(length(x))) by default. 'reflection' transforms [x, fliplr(x)], twice as long.
imodwt: The inverse maximal overlap transform.
    x = imodwt(w)
    x = imodwt(w, wname)
    x = imodwt(w, LoR, HiR)
    x = imodwt(..., 'reflection')
    * The wavelet is 'sym4' by default; 'reflection' returns the first half, as modwt's 'reflection' doubled the signal.
modwtmra: The multiresolution analysis of a maximal overlap transform.
    mra = modwtmra(w)
    mra = modwtmra(w, wname)
    mra = modwtmra(..., 'reflection')
    * Rows D_1, ..., D_J and S_J: the inverse of each row of w alone. They sum to the signal, and each is as long.
wavefun: The scaling function and wavelet of a discrete wavelet.
    [phi, psi, x] = wavefun(wname)
    [phi, psi, x] = wavefun(wname, iter)
    [phi1, psi1, phi2, psi2, x] = wavefun(wname, iter)
    wavefun(wname, iter)
    * By the cascade algorithm, iter (8) times: x = (0:m-1)/2^iter over the support. A biorthogonal wavelet gives the decomposition pair (1) and the reconstruction pair (2). With no outputs it draws them.
centfrq: The centre frequency of a wavelet.
    f = centfrq(wname)
    f = centfrq(wname, iter)
    * Where the spectrum of psi (from wavefun, 8 iterations) is largest, in cycles per unit of x.
scal2frq: The frequencies of the scales of a wavelet.
    f = scal2frq(a, wname)
    f = scal2frq(a, wname, delta)
    * centfrq(wname)./(a*delta), delta the sampling period (1).
cwt: The continuous wavelet transform.
    [wt, f, coi] = cwt(x)
    [wt, f, coi] = cwt(x, fs)
    [wt, f, coi] = cwt(x, wname, fs)
    [wt, f, coi] = cwt(..., Name, Value)
    cwt(...)
    * wname is 'morse' (the default: symmetry gamma 3, time-bandwidth product P^2 60), 'amor' (analytic Morlet, peak at 6 rad/sample at scale 1) or 'bump' (5 and width 0.6). Each is defined by its spectrum, zero at negative frequencies, with peak 2: a cosine of amplitude A gives abs(wt) = A at its frequency. Computed by FFT, x first extended at both ends by half its length, mirrored (ExtendSignal false to not).
    * Scales, smallest first, VoicesPerOctave (10) to an octave: from the one at which the wavelet's spectrum falls to half its peak at the Nyquist frequency, up to the one at which two of its time standard deviations make half the signal's length; FrequencyLimits [f1 f2] narrows them. f are the scales' peak frequencies (Hz with fs, else cycles per sample); WaveletParameters [gamma P^2] shape the Morse wavelet.
    * coi is the cone of influence: at each time, the frequency below which the wavelet (sqrt(2) standard deviations wide) reaches past an end. With no outputs, the magnitude scalogram is drawn with the cone dashed.
icwt: The signal from its continuous wavelet transform.
    xrec = icwt(wt)
    xrec = icwt(wt, wname)
    xrec = icwt(wt, wname, f, freqrange)
    xrec = icwt(..., 'SignalMean', m, 'VoicesPerOctave', nv)
    * 2/C times log(2)/nv times the sum of the real parts of the rows, C the wavelet's admissibility constant (the integral of its spectrum divided by frequency): exact in the limit of many voices and all scales, close otherwise; the mean, which cwt does not see, is added from SignalMean. f and freqrange keep only the rows within the range.
cwtfreqbounds: The frequency range of cwt's scales.
    [minf, maxf] = cwtfreqbounds(N)
    [minf, maxf] = cwtfreqbounds(N, fs, Name, Value)
    * For N samples, as cwt chooses its scales; 'Wavelet', 'VoicesPerOctave' and 'WaveletParameters' as in cwt.
wthresh: Soft or hard thresholding.
    Y = wthresh(X, 's', T)
    Y = wthresh(X, 'h', T)
    * Soft: sign(X).*max(abs(X) - T, 0). Hard: X where abs(X) > T, else 0.
wnoisest: The noise level of a decomposition's details.
    stdc = wnoisest(c, l)
    stdc = wnoisest(c, l, s)
    * median(abs(cD))/0.6745 at each level in s (1 by default): the standard deviation of Gaussian noise, robust to the signal's few large coefficients.
thselect: A threshold for denoising.
    thr = thselect(x, tptr)
    * For noise of unit variance: 'sqtwolog' sqrt(2 log(n)); 'minimaxi' 0.3936 + 0.1829 log2(n) (0 for n up to 32); 'rigrsure' the threshold minimizing Stein's unbiased estimate of the risk of soft thresholding; 'heursure' sqtwolog when the signal looks like noise (sum(x.^2) - n under n^(1/2) log2(n)^1.5), else the smaller of the two.
wden: Denoising by level-dependent thresholds.
    [xd, cxd, lxd] = wden(x, tptr, sorh, scal, n, wname)
    [xd, cxd, lxd] = wden(c, l, tptr, sorh, scal, n, wname)
    * x decomposed to level n (or c, l given); at each level the details get the threshold thselect(cD/s, tptr)*s, s 1 ('one'), the noise of level 1 ('sln') or of that level ('mln'), soft ('s') or hard ('h'); the approximation is kept.
ddencmp: The default denoising values.
    [thr, sorh, keepapp] = ddencmp('den', 'wv', x)
    * thr = sqrt(2 log(n)) times the noise of x (median of the absolute level-1 db1 details over 0.6745), soft thresholding, approximation kept.
wdenoise: Wavelet denoising.
    xden = wdenoise(x)
    xden = wdenoise(x, level)
    [xden, denoisedcfs, origcfs] = wdenoise(..., Name, Value)
    wdenoise(...)
    * x (or each column of a matrix) decomposed to level (the smaller of floor(log2(n)) and wmaxlev) by 'Wavelet' ('sym4'); each level's details thresholded with the noise estimated from level 1 ('NoiseEstimate' 'LevelIndependent') or each level ('LevelDependent'); the approximation kept. The coefficients come back as cells, level 1 first and the approximation last.
    * DenoisingMethod: 'Bayes' (the default; empirical Bayes after Johnstone and Silverman: a prior mixing zero with a Laplace density of scale 0.5, its weight per level by marginal maximum likelihood, no lower than the weight whose threshold is the universal one; ThresholdRule 'Median' (posterior median), 'Mean', 'Soft' or 'Hard'), 'SURE', 'UniversalThreshold' (sqrt(2 log(n))), 'Minimax' (soft by default, or 'Hard'), 'BlockJS' (block James-Stein: blocks of floor(log(n)), lambda 4.50524) and 'FDR' or {'FDR', q} (false discovery rate q, 0.05, hard).
    * With no outputs it draws the signal and the denoised one.
wcodemat: A matrix coded for display.
    Y = wcodemat(X)
    Y = wcodemat(X, nb, opt, absol)
    * Whole numbers 1..nb (16) in proportion to abs(X) (to X when absol is 0), scaled over the whole matrix ('mat'), each row ('row') or each column ('col'): for image(Y) with a colormap of nb colours.
'''


def _parse(text):
    table = {}
    name = None
    for line in text.split('\n'):
        if not line.strip() or line.startswith('#'):
            continue
        if line.startswith('    '):
            body = line[4:]
            if body.startswith('* '):
                table[name][2].append(body[2:])
            else:
                table[name][1].append(body)
        else:
            name, summary = line.split(': ', 1)
            table[name] = (summary, [], [])
    return {k: (s, forms, '\n'.join(notes)) for k, (s, forms, notes) in table.items()}


HELP = _parse(_TEXT)


# The functions of each distribution (normpdf, normcdf, norminv, normrnd,
# normstat, and normfit and normlike where there are such): its prefix, its
# name, and its parameters (name, meaning, the value when it is left out).
_DISTS = (
    ('norm', 'normal', (('mu', 'the mean', '0'), ('sigma', 'the standard deviation', '1'))),
    ('logn', 'lognormal', (('mu', 'the mean of log(x)', '0'), ('sigma', 'the standard deviation of log(x)', '1'))),
    ('exp', 'exponential', (('mu', 'the mean', '1'),)),
    ('gam', 'gamma', (('a', 'the shape', None), ('b', 'the scale', '1'))),
    ('beta', 'beta', (('a', 'the first shape', None), ('b', 'the second shape', None))),
    ('wbl', 'Weibull', (('A', 'the scale', '1'), ('B', 'the shape', '1'))),
    ('unif', 'continuous uniform', (('a', 'the lower limit', '0'), ('b', 'the upper limit', '1'))),
    ('unid', 'discrete uniform', (('N', 'the largest value (the values are 1 to N)', None),)),
    ('bino', 'binomial', (('N', 'the number of trials', None), ('p', 'the probability of success', None))),
    ('poiss', 'Poisson', (('lambda', 'the mean', None),)),
    ('geo', 'geometric', (('p', 'the probability of success (x counts the failures before the first success)', None),)),
    ('nbin', 'negative binomial', (('R', 'the number of successes', None),
                                   ('p', 'the probability of success (x counts the failures before the Rth success)', None))),
    ('hyge', 'hypergeometric', (('M', 'the size of the population', None), ('K', 'the number of successes in it', None),
                                ('N', 'the number drawn', None))),
    ('chi2', 'chi-square', (('nu', 'the degrees of freedom', None),)),
    ('ncx2', 'noncentral chi-square', (('nu', 'the degrees of freedom', None), ('delta', 'the noncentrality', None))),
    ('t', "Student's t", (('nu', 'the degrees of freedom', None),)),
    ('nct', 'noncentral t', (('nu', 'the degrees of freedom', None), ('delta', 'the noncentrality', None))),
    ('f', 'F', (('nu1', 'the numerator degrees of freedom', None), ('nu2', 'the denominator degrees of freedom', None))),
    ('ncf', 'noncentral F', (('nu1', 'the numerator degrees of freedom', None), ('nu2', 'the denominator degrees of freedom', None),
                             ('delta', 'the noncentrality', None))),
    ('ev', 'extreme value (of minima, Gumbel)', (('mu', 'the location', '0'), ('sigma', 'the scale', '1'))),
    ('gev', 'generalized extreme value', (('k', 'the shape', None), ('sigma', 'the scale', None), ('mu', 'the location', None))),
    ('gp', 'generalized Pareto', (('k', 'the shape', None), ('sigma', 'the scale', '1'), ('theta', 'the threshold', '0'))),
    ('rayl', 'Rayleigh', (('B', 'the scale', '1'),)),
)
_DISCRETE = {'unid', 'bino', 'poiss', 'geo', 'nbin', 'hyge'}
_FITS = {'logn', 'gam', 'beta', 'wbl', 'ev', 'gev', 'gp', 'rayl', 'nbin', 'exp', 'poiss'}
_LIKES = {'norm', 'logn', 'exp', 'gam', 'beta', 'wbl', 'ev', 'gev', 'gp', 'nbin'}


def _distribution_help():
    table = {}
    for code, name, params in _DISTS:
        args = ', '.join(p[0] for p in params)
        given = '; '.join(f'{p}, {meaning}' + (f' ({d} when left out)' if d is not None else '') for p, meaning, d in params)
        pnote = f'The parameters: {given}. Arrays of one size and scalars combine element by element.'
        if code in _DISCRETE:
            table[code + 'pdf'] = (f'The probabilities of the {name} distribution (its probability mass function).',
                                   [f'y = {code}pdf(x, {args})'], pnote)
        else:
            table[code + 'pdf'] = (f'The probability density of the {name} distribution.', [f'y = {code}pdf(x, {args})'], pnote)
        table[code + 'cdf'] = (f'The cumulative distribution function of the {name} distribution.',
                               [f'p = {code}cdf(x, {args})', f"q = {code}cdf(x, {args}, 'upper')"],
                               "With 'upper', the probability above x, computed as such (more accurate than 1 - p far out "
                               'in the tail).\n' + pnote)
        table[code + 'inv'] = (f'The quantiles of the {name} distribution: the inverse of its cdf.', [f'x = {code}inv(p, {args})'],
                               ('The smallest whole x whose cdf reaches p.\n' if code in _DISCRETE else '') + pnote)
        table[code + 'rnd'] = (f'Random numbers from the {name} distribution.',
                               [f'r = {code}rnd({args})', f'r = {code}rnd({args}, m, n)', f'r = {code}rnd({args}, [m n ...])'],
                               'The numbers come from the generator that rng sets; without a size, r has the size of the '
                               'parameters.\n' + pnote)
        table[code + 'stat'] = (f'The mean and the variance of the {name} distribution.', [f'[m, v] = {code}stat({args})'], pnote)
        if code in _FITS:
            note = (f'phat has the estimates in the order {code}pdf takes them; pci has the intervals\' lower ends in its first '
                    'row and their upper ends in its second (95% unless alpha is given).')
            if code == 'logn':
                note += ' sigma is the unbiased estimate, as normfit gives for log(x); mu is the mean of log(x).'
            elif code == 'gp':
                note = 'The data are exceedances over the threshold (theta 0): phat = [k sigma]. ' + note
            else:
                note = 'Maximum likelihood estimates. ' + note
            table[code + 'fit'] = (f'Estimates of the {name} distribution\'s parameters from data, with confidence intervals.',
                                   [f'phat = {code}fit(x)', f'[phat, pci] = {code}fit(x, alpha)'], note)
        if code in _LIKES:
            table[code + 'like'] = (f'The negative log-likelihood of parameters of the {name} distribution for data.',
                                    [f'nlogL = {code}like(params, x)', f'[nlogL, acov] = {code}like(params, x)'],
                                    f'params has the parameters in the order {code}pdf takes them'
                                    + (' (the threshold 0: [k sigma])' if code == 'gp' else '')
                                    + '; acov approximates their covariance (the inverse of the observed information).')
    return table


HELP.update(_distribution_help())


# ---- the qualifications of a test case (verifyEqual, assertEqual, fatalAssertEqual, assumeEqual, ...) ------------
_QUALS = (
    ('Equal', 'the actual value equals the expected one', ['actual, expected', "actual, expected, 'AbsTol', t", "actual, expected, 'RelTol', t"],
     'Equal means of the same class and size, and the same values: NaN equals NaN; numbers within the tolerance when one is given '
     '(each element |a - e| <= AbsTol or <= RelTol*|e|); cells and structs compared element by element, field by field (in any order).'),
    ('NotEqual', 'the values are not equal', ['actual, notExpected'], 'Equal as for verifyEqual.'),
    ('True', 'the value is true', ['actual'], 'It must be a logical scalar: 1 is not true here.'),
    ('False', 'the value is false', ['actual'], 'It must be a logical scalar.'),
    ('Error', 'a function throws an error', ['fh, identifier'], 'fh is called with no inputs; the error must have that identifier.'),
    ('Warning', 'a function issues a warning', ['fh, identifier', '[out1, ...] = ...(fh, identifier)'],
     "fh is called with no inputs; one of its warnings must have that identifier. Its warnings are kept, not shown; its outputs are given back."),
    ('WarningFree', 'a function issues no warning', ['fh', '[out1, ...] = ...(fh)'], "fh is called with no inputs; its outputs are given back."),
    ('Empty', 'the value is empty', ['actual'], 'Empty: a size of 0 in some dimension.'),
    ('NotEmpty', 'the value is not empty', ['actual'], ''),
    ('Size', 'the value has a size', ['actual, expectedSize'], 'expectedSize is a row of the sizes, as size gives.'),
    ('Length', 'the value has a length', ['actual, n'], 'The length is that of its longest dimension (0 when empty).'),
    ('NumElements', 'the value has a number of elements', ['actual, n'], ''),
    ('Class', 'the value is of a class', ['actual, className'], 'Exactly that class: a subclass does not pass (see ...InstanceOf).'),
    ('InstanceOf', 'the value is of a class or one of its subclasses', ['actual, className'], 'As isa.'),
    ('GreaterThan', 'every value is greater than a floor', ['actual, floor'], 'Element by element; an empty value fails.'),
    ('GreaterThanOrEqual', 'every value is at least a floor', ['actual, floor'], 'Element by element; an empty value fails.'),
    ('LessThan', 'every value is less than a ceiling', ['actual, ceiling'], 'Element by element; an empty value fails.'),
    ('LessThanOrEqual', 'every value is at most a ceiling', ['actual, ceiling'], 'Element by element; an empty value fails.'),
    ('ReturnsTrue', 'a function gives true', ['fh'], 'fh is called with no inputs and must give a logical scalar true.'),
    ('Substring', 'text holds a piece of text', ['actual, substring'], 'Both are char vectors or string scalars; case counts.'),
    ('Matches', 'text matches a regular expression', ['actual, expression'], 'Somewhere in the text, as regexp finds it.'),
    ('Fail', 'nothing: it always fails', [''], 'For a branch a test must not reach.'),
    ('SameHandle', 'two values are the same handle object', ['actual, expected'], ''),
    ('NotSameHandle', 'two values are not the same handle object', ['actual, notExpected'], ''),
)
_QUAL_KINDS = (
    ('verify', 'A verification', 'A failure is recorded and the test goes on.'),
    ('assert', 'An assertion', 'A failure is recorded and ends the test.'),
    ('fatalAssert', 'A fatal assertion', 'A failure is recorded and ends the test, and the tests after it in the run are not run.'),
    ('assume', 'An assumption', 'A failure ends the test, as incomplete (filtered), not failed.'),
)


def _qualification_help():
    table = {}
    for kind, what, effect in _QUAL_KINDS:
        for check, says, forms, note in _QUALS:
            name = kind + check
            calls = []
            for f in forms:
                if f.startswith('['):
                    outs, args = f.split(' = ...(')
                    calls.append(f'{outs} = {name}(testCase, {args}')
                else:
                    calls.append(f'{name}(testCase' + (f', {f})' if f else ')'))
            calls.append(f'{name}(testCase, ..., diagnostic)')
            calls.append(f'testCase.{name}(...)')
            notes = [f'{effect} {note}'.strip(), 'diagnostic is text shown with a failure. With matlab.unittest.TestCase.forInteractiveUse, it says whether it passed.']
            table[name] = (f'{what} that {says}.', calls, '\n'.join(notes))
    return table


HELP.update(_qualification_help())


from .howtext import HOW  # noqa: E402,F401  (how PyLAB computes each function)
