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
classdef: Not available here: classes of your own cannot be defined. Use functions, structs and containers.Map.
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
expm1: exp(x) - 1, accurate for small x.
    y = expm1(x)
log: The natural logarithm (complex for negative numbers).
    y = log(x)
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
ismissing: True for missing elements: NaN, <missing> strings, blanks in a char array, empty text in a cell.
    tf = ismissing(A)
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
    M = mean(A, 'all')
    M = mean(..., 'omitnan')
    m = mean(pd)
    * mean(pd) is the mean of a distribution object (makedist, fitdist); so too median, std, var and iqr.
median: The middle value.
    M = median(A)
    M = median(A, dim)
    M = median(..., 'omitnan')
    m = median(pd)
mode: The most frequent value (the smallest of those tied).
    M = mode(A)
    M = mode(A, dim)
    [M, F] = mode(...)
std: The standard deviation (normalized by N-1, or N with w = 1).
    s = std(A)
    s = std(A, w)
    s = std(A, w, dim)
    s = std(..., 'omitnan')
    s = std(pd)
var: The variance (normalized by N-1, or N with w = 1).
    v = var(A)
    v = var(A, w)
    v = var(A, w, dim)
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
sortrows: Sort the rows of a matrix by its columns.
    B = sortrows(A)
    B = sortrows(A, column)
    B = sortrows(A, -column)
    [B, I] = sortrows(...)
issorted: True when the elements are in sorted order.
    tf = issorted(A)
unique: The distinct values, sorted (or in the order first met).
    C = unique(A)
    C = unique(A, 'stable')
    C = unique(A, 'rows')
    [C, ia, ic] = unique(...)
ismember: Which elements of A are found in B, and where.
    tf = ismember(A, B)
    [tf, loc] = ismember(A, B)
    tf = ismember(A, B, 'rows')
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
corrcoef: Correlation coefficients.
    R = corrcoef(A)
    R = corrcoef(x, y)
    [R, P] = corrcoef(...)
trapz: An integral by the trapezoidal rule.
    Q = trapz(y)
    Q = trapz(x, y)
    Q = trapz(..., dim)
cumtrapz: The running integral by the trapezoidal rule.
    Q = cumtrapz(y)
    Q = cumtrapz(x, y)
quantile: Quantiles of a sample.
    Q = quantile(X, p)
    Q = quantile(X, p, dim)
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
rescale: Scale values linearly to fill [0, 1], or another interval.
    R = rescale(A)
    R = rescale(A, l, u)
normalize: Centre and scale data (z-scores by default).
    N = normalize(A)
    N = normalize(A, dim)
    N = normalize(..., 'range')

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
    * pd is a distribution object (makedist, fitdist); name is a distribution's name ('Normal', 'Poisson', 't', ...) with its parameters in the order its own function takes them (normpdf(x, mu, sigma)).
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
    * The numbers come from the generator that rng sets.
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

# ---- linear algebra --------------------------------------------------------------------------
inv: The inverse of a square matrix.
    Y = inv(A)
    * A \ b is faster and more accurate than inv(A)*b.
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
    [V, D] = eigs(...)
svd: The singular value decomposition, A = U*S*V'.
    s = svd(A)
    [U, S, V] = svd(A)
    [U, S, V] = svd(A, 'econ')
svds: Some singular values (the largest by default).
    s = svds(A)
    s = svds(A, k)
    [U, S, V] = svds(...)
qr: The QR decomposition, A = Q*R.
    [Q, R] = qr(A)
    [Q, R] = qr(A, 0)
    [Q, R, P] = qr(A)
    R = qr(A)
lu: The LU decomposition with row pivoting.
    [L, U] = lu(A)
    [L, U, P] = lu(A)
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
lsqnonneg: Least squares with x >= 0.
    x = lsqnonneg(C, d)
    [x, resnorm] = lsqnonneg(C, d)
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
    S = sparse(m, n)
    * Sparse matrices are held as full ones here: the results are the same, the memory is not saved.
full: A sparse matrix as a full one.
    A = full(S)
issparse: True for a sparse matrix (never, here: they are held full).
    tf = issparse(S)
nzmax: The room for nonzero elements (their number, here).
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

# ---- special functions -----------------------------------------------------------------------
gamma: The gamma function; gamma(n+1) = n!.
    y = gamma(x)
gammaln: The logarithm of the gamma function, without overflow.
    y = gammaln(x)
gammainc: The regularized incomplete gamma function.
    y = gammainc(x, a)
    y = gammainc(x, a, 'upper')
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
residue: Partial fractions of a ratio of polynomials.
    [r, p, k] = residue(b, a)
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
del2: The discrete Laplacian, divided by 4 in two dimensions.
    L = del2(U)
    L = del2(U, h)

# ---- interpolation ---------------------------------------------------------------------------
interp1: Interpolation in one dimension.
    vq = interp1(x, v, xq)
    vq = interp1(x, v, xq, method)
    vq = interp1(x, v, xq, method, 'extrap')
    vq = interp1(x, v, xq, method, extrapval)
    pp = interp1(x, v, method, 'pp')
    * method is 'linear' (the default), 'nearest', 'next', 'previous', 'pchip', 'cubic', 'makima' or 'spline'.
interp2: Interpolation on a 2-D grid.
    Vq = interp2(X, Y, V, Xq, Yq)
    Vq = interp2(V, Xq, Yq)
    Vq = interp2(..., method)
    Vq = interp2(..., method, extrapval)
interpn: Interpolation on a grid in any number of dimensions.
    Vq = interpn(X1, X2, ..., V, Xq1, Xq2, ...)
    Vq = interpn(..., method)
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
fminunc: The minimum of a smooth function of several variables, by a quasi-Newton method.
    x = fminunc(fun, x0)
    x = fminunc(fun, x0, options)
    [x, fval, exitflag, output] = fminunc(...)
fmincon: The minimum of a function under bounds and linear or nonlinear constraints.
    x = fmincon(fun, x0, A, b)
    x = fmincon(fun, x0, A, b, Aeq, beq, lb, ub)
    x = fmincon(fun, x0, A, b, Aeq, beq, lb, ub, nonlcon)
    x = fmincon(fun, x0, A, b, Aeq, beq, lb, ub, nonlcon, options)
    [x, fval, exitflag, output] = fmincon(...)
fsolve: Solve a system of nonlinear equations F(x) = 0.
    x = fsolve(fun, x0)
    x = fsolve(fun, x0, options)
    [x, fval, exitflag, output] = fsolve(...)
lsqcurvefit: Fit the parameters of a function to data by nonlinear least squares.
    x = lsqcurvefit(fun, x0, xdata, ydata)
    x = lsqcurvefit(fun, x0, xdata, ydata, lb, ub)
    [x, resnorm, residual, exitflag] = lsqcurvefit(...)
lsqnonlin: Nonlinear least squares: the x that minimizes sum(fun(x).^2).
    x = lsqnonlin(fun, x0)
    x = lsqnonlin(fun, x0, lb, ub)
    [x, resnorm, residual, exitflag] = lsqnonlin(...)
linprog: Linear programming: minimize f'*x under linear constraints and bounds.
    x = linprog(f, A, b)
    x = linprog(f, A, b, Aeq, beq, lb, ub)
    [x, fval, exitflag] = linprog(...)
optimset: Make or change a structure of options for the solvers.
    options = optimset('Name', value, ...)
    options = optimset(oldopts, 'Name', value, ...)
    options = optimset('fminsearch')
optimget: An option's value from an options structure.
    v = optimget(options, 'Name')
    v = optimget(options, 'Name', default)
optimoptions: Options for a solver, by name and value.
    options = optimoptions('fminunc', 'Name', value, ...)
integral: A definite integral, by adaptive quadrature.
    q = integral(fun, a, b)
    q = integral(fun, a, b, 'RelTol', r, 'AbsTol', t)
    q = integral(fun, a, b, 'ArrayValued', true)
    * fun takes a vector and returns a vector of the same size; Inf is a limit too.
integral2: A double integral; the inner limits may be functions.
    q = integral2(fun, xmin, xmax, ymin, ymax)
integral3: A triple integral.
    q = integral3(fun, xmin, xmax, ymin, ymax, zmin, zmax)
quad: A definite integral by adaptive Simpson quadrature (older; integral is preferred).
    q = quad(fun, a, b)
    q = quad(fun, a, b, tol)
quadl: A definite integral by adaptive Lobatto quadrature (older; integral is preferred).
    q = quadl(fun, a, b)
quadgk: A definite integral by adaptive Gauss-Kronrod quadrature.
    q = quadgk(fun, a, b)
    [q, errbnd] = quadgk(fun, a, b)
quad2d: A double integral over a region with curved limits.
    q = quad2d(fun, a, b, c, d)
dblquad: A double integral over a rectangle (older; integral2 is preferred).
    q = dblquad(fun, xmin, xmax, ymin, ymax)
triplequad: A triple integral over a box (older; integral3 is preferred).
    q = triplequad(fun, xmin, xmax, ymin, ymax, zmin, zmax)

# ---- differential equations ------------------------------------------------------------------
ode45: Solve an ODE system y' = f(t, y): explicit Runge-Kutta (4,5), for nonstiff problems.
    [t, y] = ode45(odefun, tspan, y0)
    [t, y] = ode45(odefun, tspan, y0, options)
    sol = ode45(...)
    [t, y, te, ye, ie] = ode45(..., options)
    * odefun(t, y) returns a column; tspan with more than two values asks for the solution at those times.
ode23: Solve a nonstiff ODE system by the Runge-Kutta (2,3) pair, for loose tolerances.
    [t, y] = ode23(odefun, tspan, y0)
    [t, y] = ode23(odefun, tspan, y0, options)
ode113: Solve a nonstiff ODE system by a variable-order Adams method.
    [t, y] = ode113(odefun, tspan, y0)
    [t, y] = ode113(odefun, tspan, y0, options)
ode78: Solve a nonstiff ODE system by a Runge-Kutta (7,8) pair, for tight tolerances.
    [t, y] = ode78(odefun, tspan, y0, options)
ode89: Solve a nonstiff ODE system by a Runge-Kutta (8,9) pair, for very tight tolerances.
    [t, y] = ode89(odefun, tspan, y0, options)
ode15s: Solve a stiff ODE system (or one with a mass matrix) by a variable-order BDF method.
    [t, y] = ode15s(odefun, tspan, y0)
    [t, y] = ode15s(odefun, tspan, y0, options)
ode23s: Solve a stiff ODE system by a Rosenbrock method.
    [t, y] = ode23s(odefun, tspan, y0, options)
ode23t: Solve a moderately stiff ODE system by the trapezoidal rule.
    [t, y] = ode23t(odefun, tspan, y0, options)
ode23tb: Solve a stiff ODE system by TR-BDF2.
    [t, y] = ode23tb(odefun, tspan, y0, options)
ode15i: Solve an implicit system f(t, y, y') = 0.
    [t, y] = ode15i(odefun, tspan, y0, yp0)
    [t, y] = ode15i(odefun, tspan, y0, yp0, options)
    sol = ode15i(...)
    * Here y' is found from f(t, y, y') = 0 at each step, which needs df/dy' to be nonsingular: implicit ODEs, not differential-algebraic systems.
odeset: Make or change the options for the ODE solvers.
    options = odeset('RelTol', 1e-6, 'AbsTol', 1e-9, ...)
    options = odeset(oldopts, 'Name', value, ...)
    * Among the names: RelTol, AbsTol, MaxStep, InitialStep, Events, Mass, Jacobian, NonNegative, OutputFcn.
odeget: An option's value from an ODE options structure.
    v = odeget(options, 'Name')
    v = odeget(options, 'Name', default)
deval: Evaluate the solution structure of an ODE solver at new times.
    y = deval(sol, t)
    y = deval(sol, t, idx)
odextend: Carry the solution structure of an ODE solver on to a later time.
    sol = odextend(sol, odefun, tfinal)
    sol = odextend(sol, [], tfinal)
    sol = odextend(sol, odefun, tfinal, y0)
    sol = odextend(sol, odefun, tfinal, y0, options)

# ---- text ------------------------------------------------------------------------------------
char: A character array, from numbers (character codes), strings or cells of text.
    c = char(x)
    c = char(s1, s2, ...)
string: A string array, from text, numbers or cells.
    s = string(x)
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
join: Join the strings of an array with a separator.
    s = join(parts)
    s = join(parts, delimiter)
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
containers.Map: A map from keys (text or numbers) to values.
    M = containers.Map()
    M = containers.Map(keys, values)
    M = containers.Map('KeyType', 'char', 'ValueType', 'any')
    * M(key) reads and sets values; M.Count is the number of keys; M is a handle: copies share it.
keys: The keys of a map, sorted, as a cell row.
    k = keys(M)
values: The values of a map, in the order of its keys, or those of some keys.
    v = values(M)
    v = values(M, keySet)
isKey: True when a map has a key (or which of several it has).
    tf = isKey(M, key)
remove: Remove keys from a map.
    remove(M, key)
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
    tf = isobject(x)
double: Convert to double precision.
    y = double(x)
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
str2func: A function handle from its text.
    fh = str2func('name')
    fh = str2func('@(x) x.^2')
feval: Call a function by handle or by name.
    [y1, y2, ...] = feval(fun, x1, x2, ...)

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
    names = who
whos: List the variables with their sizes, bytes and classes.
    whos
    s = whos
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
    * Attributes include 'scalar', 'vector', 'row', 'column', 'nonempty', 'real', 'finite', 'nonnan', 'integer', 'positive', 'nonnegative', 'increasing', {'size', [m n]}, {'>=', v}.
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
diary: Accepted, with no effect: copy the Command Window with its menu instead.
    diary filename
beep: Accepted, with no effect.
    beep
profile: Accepted, with no effect: use tic and toc to time code.
    profile on | off
exit: Stop the program; the page itself is closed with its browser tab.
    exit
quit: Stop the program; the page itself is closed with its browser tab.
    quit
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
open: Open a file: program files in the Editor, MAT-files into the workspace.
    open filename
run: Run a script file.
    run filename
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
    C = textscan(text, format, 'Delimiter', ',', 'HeaderLines', 1)
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
    * String arrays load. A variable that cannot be read is left out with a warning and the others load: other objects, such as tables and datetimes, are not read. Sparse matrices load as full ones.
    * A text file of numbers loads as a variable named after the file; -mat reads a MAT-file of any name.
save: Save variables to a MAT-file (or to a text file with -ascii).
    save filename
    save filename x y
    save(filename, 'x', 'y')
    save filename x -append
    save filename x -ascii
    * -append adds to what the file holds; it refuses, saving nothing, rather than lose a variable of the file it cannot read.
    * The file is of version 7 (compressed), or 6 or 4 when asked; -v7.3 also writes version 7. Function handles and objects are not saved.
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
    * LineSpec joins a line style (- -- : -.), a marker (o + * . x s d ^ v > < p h) and a colour (r g b c m y k w), e.g. 'r--o'.
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
    h = histogram(...)
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
    ax = subplot(...)
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
ytickangle: Turn the labels of the y ticks.
    ytickangle(angle)
grid: Show or hide the grid lines.
    grid on | off | minor
    grid
box: Show or hide the box round the axes.
    box on | off
daspect: The data aspect ratio: how long one unit is on each axis.
    daspect([1 1 1])
    r = daspect
pbaspect: The plot box aspect ratio.
    pbaspect([1 1 1])
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
annotation: Text, a line, an arrow or a box on the figure, in normalized figure units.
    annotation('textbox', [x y w h], 'String', s)
    annotation('arrow', [x1 x2], [y1 y2])
    annotation('line', [x1 x2], [y1 y2])
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
findall: Graphics objects with given properties, hidden ones included.
    h = findall(parent, 'Name', value, ...)
allchild: Every child of a graphics object.
    h = allchild(parent)
ancestor: The ancestor of a graphics object of a given type.
    p = ancestor(h, 'figure' | 'axes')
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
getframe: Not available here: write a picture with saveas or exportgraphics.
    F = getframe
saveas: Save a figure as a picture file (PNG or SVG, by the extension).
    saveas(fig, filename)
    saveas(fig, filename, format)
exportgraphics: Save a figure or axes as a picture file.
    exportgraphics(obj, filename)
    exportgraphics(obj, filename, 'Resolution', dpi)
print: Save the current figure as a picture file.
    print(filename, '-dpng')
    print(fig, filename, '-dsvg')
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
    * uiwait(h) waits until it is closed; 'modal' as the last input keeps it in front.
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
dialog: An empty window for a dialog of one's own making.
    d = dialog('Name', 'Settings', 'Position', [300 300 250 150])
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
stop: Stop a timer.
    stop(t)
wait: Wait (letting callbacks run) until a timer stops.
    wait(t)
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
