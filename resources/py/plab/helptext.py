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
parfor: A for loop whose passes may run in parallel; here they run one after another.
    parfor k = 1:n, statements, end
spmd: A block for parallel workers; here its body runs once.
    spmd, statements, end
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
median: The middle value.
    M = median(A)
    M = median(A, dim)
    M = median(..., 'omitnan')
mode: The most frequent value (the smallest of those tied).
    M = mode(A)
    M = mode(A, dim)
    [M, F] = mode(...)
std: The standard deviation (normalized by N-1, or N with w = 1).
    s = std(A)
    s = std(A, w)
    s = std(A, w, dim)
    s = std(..., 'omitnan')
var: The variance (normalized by N-1, or N with w = 1).
    v = var(A)
    v = var(A, w)
    v = var(A, w, dim)
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
    * A variable that cannot be read is left out with a warning and the others load: objects such as string arrays, tables and datetimes are not read. Sparse matrices load as full ones.
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
isprop: True when an object has a property.
    tf = isprop(h, name)
drawnow: Draw the figures now (while a long program runs).
    drawnow
    drawnow limitrate
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
uistack: Accepted, with no effect.
    uistack(h, 'top')
movegui: Accepted, with no effect: drag the figure window by its title bar.
    movegui(fig, position)
whitebg: Accepted, with no effect.
    whitebg

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
